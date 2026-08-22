# clip-mvp

MVP local de cortes automáticos (YouTube Shorts / TikTok / 16:9) com IA via OpenRouter.

**Spec canônica:** [`SPEC.md`](./SPEC.md)

## Status

Pipeline `core` implementado em `src/clip_mvp/` (download → transcrição →
candidatos → score → render → face track → diarização → meta.json →
feedback), seguindo a ordem de build da [SPEC §12](./SPEC.md#12-ordem-de-build).

Todo estágio reporta progresso estruturado com **estimativa de tempo restante**,
consumido pela CLI, pela API HTTP e pela UI web em React (`clip serve`).

## Instalação

Requisitos: Python 3.11+, `ffmpeg`/`ffprobe` no PATH e Node 20+ (só para buildar
a interface).

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .              # CLI + API
pip install -e '.[facetrack]' # + MediaPipe/OpenCV para o vertical_facetrack
cp .env.example .env          # opcional: OPENROUTER_API_KEY= (também dá para colar na UI)
```

Sem MediaPipe o `vertical_facetrack` não é gerado (o job avisa e segue com
`vertical_center` + `horizontal_16x9`).

## Interface web

```bash
cd web && npm install && npm run build && cd ..
clip serve                    # http://127.0.0.1:8765
```

O build fica em `web/dist/`, que é gitignorado: depois de clonar o repo é preciso
buildar uma vez, senão `clip serve` sobe a API e serve uma página explicando isso
(`GET /api/health` também responde `ui_built: false`).

Desenvolvendo o front, rode os dois processos (o Vite faz proxy de `/api` para a
porta default de `clip serve`; use `CLIP_MVP_API` se subir em outra):

```bash
clip serve                    # API em :8765
cd web && npm run dev         # UI em :5173 com hot reload

# API em outra porta:
clip serve --port 9000
CLIP_MVP_API=http://127.0.0.1:9000 npm run dev
```

A interface é um app React + Vite (`web/`) que consome o mesmo payload de
progresso da CLI. Com ela você:

- cola a **chave da OpenRouter** e escolhe o modelo de cada papel de IA em
  **Configurações** (STT, candidatos, score/vision, texto social, diarização) —
  qualquer id do catálogo, com busca quando a chave está salva;
- cola a URL e escolhe quantidade (**auto** / **+50%** / **fixo N**), limiar de
  score, formatos, legendas e plataformas;
- estima o custo antes de gastar (**dry-run**) e trava um **orçamento** em USD;
- acompanha o job ao vivo: percentual global, estágio atual, **minutos
  restantes**, tempo de cada estágio e status de render por corte (quais
  formatos já saíram, qual está rodando, qual teve o 9:16 descartado);
- pré-visualiza cada corte nos três formatos, com breakdown do score, janelas
  9:16/16:9 e motivo do corte — e no 9:16 pode ligar a **máscara de safe area**
  para conferir, antes de publicar, que a legenda não cai atrás da UI do
  TikTok/Shorts (mesmas frações do burn-in, SPEC §14.5);
- copia títulos, descrições e hashtags de YouTube Shorts, YouTube 16:9 e TikTok;
- baixa os `.mp4`, `.srt` e `.ass`;
- vota **bom/ruim** por corte (vai para `work/feedback.jsonl` e volta como
  few-shot nos próximos prompts);
- pede **mais cortes** ou **refaz com N** reaproveitando o cache do job;
- quando um estágio falha, vê a dica em PT-BR e um botão **Tentar de novo** —
  a tela nunca fica girando para sempre (o SSE cai para polling sozinho), e um
  job abandonado por processo morto aparece como **interrompido** com
  **Retomar de onde parou**.

Jobs criados na CLI aparecem na UI e vice-versa: o estado vive em
`work/<job_id>/status.json`.

### Chave e modelos (Configurações)

A chave **não precisa** morar só no `.env`. Em **Configurações** você cola
`OPENROUTER_API_KEY`, testa a conexão e escolhe o modelo de cada papel:

| Papel | Para quê | Default (`.env.example`) |
|-------|----------|--------------------------|
| STT / Whisper | transcrição PT-BR com timestamps | `openai/whisper-1` |
| Candidatos | trechos com contexto fechado | `google/gemini-2.5-flash` |
| Score (vision) | nota 0–100 + 3 frames | `google/gemini-2.5-flash` |
| Meta / texto social | títulos e hashtags YT/TikTok | `google/gemini-2.5-flash` |
| Diarização | speaker labels (opcional; vazio = STT) | (mesmo do STT) |

Qualquer slug da OpenRouter (`autor/modelo`, inclusive `:free`) é aceito — o
campo é texto livre. Com a chave salva, a tela busca `GET /api/v1/models` e
filtra por modalidade (áudio no STT, visão no score).

A chave é gravada **fora do repositório**, com permissão `0600`:

```
~/.config/clip-mvp/settings.json
```

(ou o caminho de `CLIP_SETTINGS_FILE` / `$XDG_CONFIG_HOME/clip-mvp/settings.json`).
A API **nunca** devolve o valor completo — só um máscara (`sk-or-…cdef`) e a
origem (`ui` ou `env`). A CLI (`clip "URL"`) lê o mesmo arquivo por cima do
`.env`, então configurar na tela vale no terminal sem reiniciar nada. Precedência:

```
default do código  <  .env  <  arquivo de settings (UI)
```

## Uso da CLI

```bash
# Roda o pipeline completo (auto: IA decide quantos cortes fazem sentido)
clip "https://youtube.com/watch?v=..."

# Pede ~50% mais cortes do que o auto escolheria (ainda respeita o limiar)
clip "https://youtube.com/watch?v=..." --more

# Força até 12 cortes (só entrega o que passar do limiar de score)
clip "https://youtube.com/watch?v=..." --count 12

# Afrouxa/aperta o limiar mínimo de score (default: 60)
clip "https://youtube.com/watch?v=..." --min-score 50

# Só os clips com score >= 80
clip "https://youtube.com/watch?v=..." --max-score-only 80

# Escolhe formatos / legendas / plataformas
clip "https://youtube.com/watch?v=..." --formats face,9x16,16x9
clip "https://youtube.com/watch?v=..." --captions burn|sidecar|both
clip "https://youtube.com/watch?v=..." --platforms yt,tiktok

# Estima custo OpenRouter e para ANTES de transcrever/gerar candidatos/vision
clip "https://youtube.com/watch?v=..." --dry-run

# Limita o gasto estimado (USD); reduz nº de candidatos ou aborta
clip "https://youtube.com/watch?v=..." --budget 2.00

# Re-run barato (reusa transcrição + candidatos em work/<job_id>/, sem re-download)
clip resume <job_id> --more
clip resume <job_id> --count 12

# Feedback (grava em work/feedback.jsonl, entra como few-shot nos próximos prompts)
clip rate <job_id> <clip_slug> good|bad --note "..."

# Corte manual por timestamp (utilitário de baixo nível)
clip cut video.mp4 12.5 45.0 out.mp4

# Progresso de um job (percentual, estágio atual, minutos restantes)
clip status <job_id>
clip status <job_id> --watch     # acompanha até terminar
clip status                      # lista os últimos jobs

# Sobe a UI web + API com progresso ao vivo
clip serve                       # http://127.0.0.1:8765

# Roda a suíte de testes (fixtures BR)
clip test
```

`clip "URL"` é equivalente a `clip run "URL"` — o entrypoint reconhece se o
primeiro argumento é um subcomando (`run`, `resume`, `rate`, `status`, `serve`,
`cut`, `test`) ou uma URL solta.

## Progresso e tempo restante

Um job de podcast longo leva minutos. Para que dê para diferenciar "está
trabalhando" de "travou", cada estágio reporta progresso estruturado:

```
download → transcribe → candidates → score → select → captions → render → meta
```

Durante a execução, `clip "URL"` desenha um painel ao vivo com barra global,
estágio atual, tempo de cada estágio concluído e status por corte (quais
formatos já saíram, qual está renderizando, qual teve o 9:16 pulado). Use
`--plain` para uma linha por atualização (bom para log/CI) ou `--quiet` para
desligar.

### Como o ETA é calculado

Cada estágio tem um modelo de custo (`base + por minuto de vídeo + por unidade
de trabalho`) calibrado para o hardware alvo. Isso dá uma estimativa já no
primeiro segundo, antes de existir qualquer medição.

A partir daí a estimativa se corrige sozinha:

- conforme cada estágio termina, o tempo real medido é comparado com a previsão
  e vira um fator de velocidade que reajusta todos os estágios seguintes — uma
  máquina ou rede mais lenta empurra o ETA para cima automaticamente;
- dentro de um estágio com unidades contáveis (blocos de STT, candidatos,
  arquivos renderizados), o ritmo medido ao vivo substitui o prior;
- o número é suavizado e limitado, para não pular na tela;
- estágios reaproveitados do cache (`resume`) entram como concluídos e saem
  da conta.

A primeira estimativa de um vídeo longo pode ser grosseira; ela se ajusta nos
primeiros estágios. O texto é PT-BR: `~4 min restantes`, `~45 s restantes`
abaixo de um minuto, `concluído` no fim.

Dois detalhes que fazem o número ser confiável em vez de decorativo:

- **Batimento.** Vários estágios são uma única chamada bloqueante: `candidates`
  é um prompt sobre a transcrição inteira, `render` gasta ~1 min por arquivo.
  Sem nada reemitindo, o ETA congelava justamente aí. O reporter reemite o
  snapshot a cada 2s (`CLIP_PROGRESS_HEARTBEAT_S`), então o ETA anda e a UI
  mostra quanto tempo o estágio atual já leva. Batimentos não entram no
  `events.jsonl`, que é o histórico de transições do job.
- **Nunca "finalizando" com trabalho pendente.** Todo estágio acaba passando da
  própria previsão, e a última unidade ainda está sendo escrita quando o
  contador já bateu no total. Um estágio em andamento sempre custa alguns
  segundos, então a tela não anuncia o fim antes da hora.

### Job interrompido

Se o processo morrer (kill, reboot, laptop fechado no meio do render), o
`status.json` continuaria dizendo `running` para sempre. Como um job vivo
reescreve esse arquivo a cada batimento — inclusive quando roda na CLI, em outro
processo — o frescor do arquivo é o que separa "morreu" de "está vivo em outro
lugar". Passado esse tempo, o job aparece como erro retriável (`stale: true`) com
**Retomar de onde parou**, que reaproveita o cache em `work/`. Nada de spinner
eterno — e isso vale tanto na API/UI quanto no `clip status`, que usa a mesma
regra.

O mesmo frescor resolve a convivência entre CLI e `clip serve`: o `job_id` vem da
URL, então colar na UI um link que já está rodando no terminal **acompanha** o job
existente em vez de disparar uma segunda execução sobre o mesmo `status.json` e a
mesma pasta `out/`. Nesse caso `retry` e `cancel` respondem 409 explicando que o
job é de outro processo (cancelar é um sinal em memória: só alcança quem
começou).

### Payload de progresso

CLI, API e UI consomem exatamente o mesmo objeto:

```json
{
  "stage": "render",
  "stage_label": "Renderizando cortes",
  "percent": 83.0,
  "stage_percent": 57.0,
  "stage_elapsed_seconds": 71.4,
  "eta_seconds": 96,
  "eta_text": "~1.5 min restantes",
  "message": "Renderizando… 4/7 arquivos",
  "clips_done": 1,
  "clips_total": 3,
  "clips": [{ "slug": "...", "score": 88, "status": "running",
              "formats": {"horizontal_16x9": "done", "vertical_center": "running",
                          "vertical_facetrack": "pending"},
              "vertical_skipped": null }],
  "stages": [{ "name": "download", "status": "done", "elapsed_seconds": 42.1 }],
  "status": "running",
  "heartbeat": false,
  "error": null
}
```

Ele é gravado em `work/<job_id>/status.json` (snapshot atual, pode ser lido por
polling) e em `work/<job_id>/events.jsonl` (histórico append-only).

### API HTTP

`clip serve` sobe a UI e a API. Progresso:

| Método | Rota | Para quê |
|--------|------|----------|
| `POST` | `/api/jobs` | cria o job (`{"url": "...", "more": false, "min_score": 60}`) |
| `GET` | `/api/jobs` | lista os jobs conhecidos (com percentual e ETA) |
| `GET` | `/api/jobs/{id}` | snapshot de progresso (polling) |
| `GET` | `/api/jobs/{id}/events` | stream SSE com o mesmo payload |
| `POST` | `/api/jobs/{id}/retry` | retoma um job (usa o cache; aceita `more`/`count`) |
| `POST` | `/api/jobs/{id}/cancel` | cancela um job em andamento |

Resultado (o que a UI mostra depois do progresso):

| Método | Rota | Para quê |
|--------|------|----------|
| `GET` | `/api/health` | ffmpeg, yt-dlp, MediaPipe, chave **mascarada** e modelos |
| `GET` | `/api/config` | regras do produto (teto de 90s, padding, faixas de N) |
| `GET` | `/api/settings` | chave mascarada + modelo de cada papel (STT, candidatos, score, meta, diarização) |
| `PUT` | `/api/settings` | grava chave e/ou modelos no arquivo de settings |
| `POST` | `/api/settings/test` | testa a conexão com a OpenRouter (chave nova ou a já salva) |
| `GET` | `/api/settings/models` | catálogo da OpenRouter (`?role=score&q=gemini`) |
| `GET` | `/api/jobs/{id}/clips` | cortes com `meta.json` e artefatos disponíveis |
| `GET` | `/api/jobs/{id}/clips/{slug}/files/{arquivo}` | preview (com `Range`) e download |
| `GET` | `/api/jobs/{id}/clips/{slug}/poster.jpg` | thumbnail (gerado sob demanda) |
| `POST` | `/api/jobs/{id}/clips/{slug}/rate` | feedback `good`/`bad` (SPEC §14.7) |

A UI usa SSE e cai sozinha para polling se o stream morrer, então ela nunca
fica congelada no último frame. Quando um estágio falha, o job entra em estado
de erro com dica em PT-BR e botão de retry — nunca fica girando para sempre.

## Saída

Cada corte selecionado vira uma pasta em `out/<score>_<slug>/`:

```
out/87_hook-fulano/
  vertical_facetrack.mp4   # 9:16 + MediaPipe (só se contexto fechado couber em ≤90s)
  vertical_center.mp4      # 9:16 center, sem tracking
  horizontal_16x9.mp4      # 16:9 trim, duração escolhida pela IA
  captions.srt             # 16:9
  captions_9x16.srt         # 9:16 (quando existir)
  captions_16x9.ass / captions_9x16.ass  # burn-in (safe area)
  meta.json                 # score, breakdown, títulos/hashtags YT+TikTok
```

## Regras duras do produto (SPEC)

- Nunca corta no meio de palavra: fronteira por word-timestamp + folga de
  200–400ms (fallback: fronteira de segmento).
- Nunca corta no meio da ideia: depois do snap, a janela é expandida até o
  contexto fechar (início de fala e pontuação terminal). A folga é limitada ao
  silêncio disponível, para não puxar a palavra do vizinho para dentro do corte.
- 9:16 sempre ≤ 90s. Se o contexto fechado passar disso, o corte procura a maior
  sub-janela alinhada a frase que caiba no teto — mas só aceita se ela ainda for
  um momento (piso de 15s, `CLIP_VERTICAL_MIN_SHRUNK_S`). Sobrando só um
  fragmento, exporta apenas `horizontal_16x9` com `vertical_skipped` no
  `meta.json`. Quando encolhe, o `meta.json` registra
  `windows.vertical_9x16.shrunk_from_16x9` e se aquela janela fecha contexto
  sozinha.
- 16:9 tem duração livre, decidida pela IA.
- **O score avalia a transcrição literal da janela final**, não o `text_excerpt`
  que o modelo de candidatos escreveu: o snap por palavra mexe nas fronteiras
  depois que aquela paráfrase foi gerada. Os primeiros 3s vão separados para o
  scorer, e um corte que abre praticamente sem fala tem o `hook` limitado de
  forma determinística.
- **Os quatro critérios do score são a nota.** SPEC §8 pede `hook`/`emocao`/
  `citavel`/`arco` de 0–25 somando 100, e isso é validado no código, não só
  pedido no prompt: cada critério é limitado à faixa e o total passa a ser a soma
  do breakdown. Sem isso um `hook: 40` entrava cru (notas em escalas diferentes
  não são comparáveis no ranking) e as penalidades determinísticas, que descontam
  do total a diferença cortada de um critério, deixavam `meta.json` com breakdown
  e nota contando histórias diferentes.
- Corte truncado não é publicável: contexto aberto tem teto de score 45 e `arco`
  no máximo 6, independentemente da nota que o modelo deu.
- Dedupe olha overlap temporal no 16:9 **e** no 9:16 (é o 9:16 que vai para o
  TikTok) e detecta a mesma ideia por vocabulário de conteúdo, não só por texto
  quase idêntico.
- Além do limiar absoluto, a seleção aplica um **piso relativo**
  (`CLIP_SCORE_RELATIVE_GAP`, default 22): num vídeo com um momento de 92, um
  corte de 61 não vai junto só porque passou dos 60. O piso nunca desce abaixo do
  mínimo da faixa da SPEC §3 e é desligado no `--count N`, que é um pedido
  explícito de quantidade.
- `--more`/`--count` nunca inventam clip fraco: qualidade > quantidade.
- Face tracking (MediaPipe) roda só no `vertical_facetrack`, nunca no
  `vertical_center`/`horizontal_16x9`.
- **O crop segue quem está falando.** A timeline de falantes sai dos speaker
  labels da própria transcrição, que já foi paga. Cada falante é ligado ao rosto
  que se mexe enquanto ele fala — mapeamento um-para-um, então dois falantes nunca
  caem no mesmo rosto — e a troca de turno vira um crossfade curto em vez de um
  corte seco. Se o modelo de STT não expõe labels, o **papel de diarização**
  (Configurações) pode apontar para um modelo que exponha: aí sim vale uma segunda
  passada de áudio, que reusa o chunking da transcrição e entra na estimativa de
  custo. Sem nada disso, o alvo é o rosto de maior área: o `activity_proxy`
  documentado na SPEC §14.6. O que de fato guiou o crop vai em
  `meta.json.speaker_matching.method`.
- `meta.json.boundaries` diz qual fronteira foi usada de verdade
  (`word_level_snapping`): o STT pode não expor palavras, e aí o snap é por
  segmento.
- Todas as chamadas de IA (STT, candidatos, score/vision, títulos, diarização)
  passam pela OpenRouter. A chave vem do arquivo de Configurações ou de
  `OPENROUTER_API_KEY` no `.env`.

## Eficiência (alvo: MacBook Pro i5 16GB)

- `work/<job_id>/` guarda vídeo, áudio, transcrição, candidatos, frames e
  diarização: `resume` não re-baixa, não re-transcreve e não re-extrai frames.
  O cache de frames é indexado pela **janela**, não pela posição do candidato:
  regenerar candidatos não reaproveita frames de outro momento (o scorer
  avaliaria o vídeo errado), e dois candidatos com a mesma janela dividem a
  extração.
- Diarização não custa chamada nenhuma: sai dos speaker labels da transcrição que
  já foi paga. `resume --more`/`--count N` regenera o pool de candidatos **só**
  quando o pedido não caberia no pool em cache (um prompt de texto; o vídeo e a
  transcrição continuam vindo do disco).
- Chamadas de rede (STT, score, títulos) rodam em paralelo limitado
  (`CLIP_NETWORK_WORKERS`, default 3); render e face tracking usam um pool
  menor (`CLIP_RENDER_WORKERS`, default 2) porque ffmpeg e MediaPipe competem
  por CPU/RAM e subir demais só faz a máquina entrar em swap.
- Vision roda **só** nos candidatos, com 3 frames reduzidos a 512px — o scorer
  precisa enxergar enquadramento e reação, não 720p.
- O dedupe compara vocabulário de conteúdo antes de qualquer comparação
  caractere-a-caractere, e limita o texto que vai para o `SequenceMatcher`:
  com excerpts de transcrição real, comparar todos os pares no tamanho cheio era
  CPU quadrática sem sinal extra.
- `--dry-run` e `--budget` decidem antes do passo caro.

### Gargalos que continuam de pé

- **Render é o teto.** MediaPipe a ~8–12fps domina o `vertical_facetrack`; com
  `CLIP_RENDER_WORKERS=2` num i5 de 4 cores, dois ffmpeg já saturam a CPU. Subir
  o pool não acelera, só aumenta a pressão de RAM.
- **STT é um round-trip por chunk de ~10 min.** Em vídeo longo é o segundo maior
  custo de tempo e depende inteiramente da latência da OpenRouter.
- **Candidatos são um único prompt** sobre a transcrição inteira (truncada em
  12k caracteres). Um podcast de 3h perde detalhe no fim da transcrição —
  particionar isso é a próxima melhoria estrutural, e não caberia nesta passada
  sem mudar a forma do prompt.
- **`out/` e `work/` não têm expiração automática** (SPEC §15 pede limpar
  `work/` antigo). Hoje é manual.

## Limites conhecidos

Coisas que funcionam, mas com fronteira definida. Estão aqui para não parecerem
bug depois:

- **Diarização depende do provider.** A timeline sai dos speaker labels do STT, e
  a maioria dos modelos Whisper-compatíveis na OpenRouter não os expõe hoje
  (SPEC §15). Sem labels o face track usa o `activity_proxy`. O proxy é o rosto de
  maior área, não análise de movimento de boca por frame.
- **Labels de falante valem dentro do bloco de STT.** Diarização vem por
  requisição, então o `SPEAKER_00` de um bloco de ~10 min não é necessariamente a
  mesma pessoa do bloco seguinte. Os labels são escopados por bloco e o
  mapeamento speaker→rosto é recalculado por corte, então um corte inteiro dentro
  de um bloco (o caso normal) fica correto; um corte que atravessa a fronteira de
  dois blocos vê mais "falantes" do que existem e cada um pega um rosto.
- **Cancelar não mata processo em andamento.** O sinal é checado entre cortes,
  entre formatos e a cada candidato avaliado, então o job para em segundos; mas o
  ffmpeg/MediaPipe que já está rodando e a chamada HTTP já em voo terminam.
- **`resume` reaproveita o cache, não o progresso.** Download, transcrição e
  candidatos vêm do disco; score, seleção, legendas, render e meta rodam de novo
  do começo. Não existe "continuar do arquivo 4/7".
- **O percentual pode recuar num retry.** Cada execução começa um reporter novo,
  então a marca d'água de percentual reinicia. Dentro de uma execução o número
  nunca volta.
- **O 9:16 encolhido tem SRT próprio** (`captions_9x16.srt`); o `captions.srt` é
  o do 16:9. São arquivos diferentes de propósito, porque as janelas podem ser
  diferentes.
- **Dedupe é temporal + vocabulário**, sem chamada de LLM para julgar "mesma
  punchline". A SPEC §14.3 aceita as duas formas; a de texto é a que roda.

## Testes

```bash
pytest                 # ou: clip test
cd web && npm run build   # typecheck do front (tsc -b) + bundle
```

Para conferir a UI sem gastar OpenRouter, `python scripts/seed_demo_job.py` roda
o pipeline inteiro com as chamadas de IA mockadas (fixture BR) e deixa um job
completo em `work/` + `out/`; depois `clip serve` e abra o job.

Os testes usam fixtures em `tests/fixtures/` (vídeo sintético + transcrição
PT-BR mockada) e mockam as chamadas de IA — não requerem rede nem
`OPENROUTER_API_KEY` real. `tests/test_server_clips.py` cobre os endpoints que a
UI consome (listagem de cortes, `Range` no preview, download, thumbnail e
feedback) e `tests/test_server.py` verifica que a UI lê exatamente os campos que
o payload de progresso promete. `tests/test_settings_store.py` e
`tests/test_server_settings.py` cobrem mascaramento da chave, persistência
`0600`, override `.env` ← UI e o contrato da tela de Configurações (sem vazar
o valor da chave).

`tests/test_fixture_expectations.py` é o teste que a SPEC §14.8 pede para rodar
**sempre que os prompts de candidatos/score mudarem**: ele roda o pipeline sobre
a fixture BR e valida as regras duras no artefato final, contra as expectativas
versionadas em `tests/fixtures/expected.json` — contexto fechado, 9:16 ≤90s sem
corte no meio de palavra, janela 9:16 dentro da 16:9, score no nome da pasta,
aspect ratio e trilha de áudio de cada export, e legenda que não vaza do corte.
A fixture existe nas duas variantes de STT: com speaker labels
(`whisper_verbose_json_diarized.json`, caminho de diarização) e sem
(`whisper_verbose_json_raw.json`, caminho `activity_proxy`).

Alvo: MacBook Pro Intel i5 16GB; ffmpeg + yt-dlp + MediaPipe locais; STT/LLM/vision no OpenRouter.
