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

Na primeira execução, sem chave configurada, a tela é um **onboarding de três
passos** (pegue a chave → cole e teste → comece), em vez do formulário de job:
o pré-requisito aparece antes, e não no meio de um job que já começou a rodar.

O resto da interface é uma coisa só: **um campo e um botão**. Colar o link
dispara um probe do vídeo que mostra título, duração e a estimativa de quantos
cortes devem sair, quanto tempo vai levar e quanto deve custar — antes de gastar
qualquer coisa. Todo o resto (quantidade, rigor, formatos, estilo de legenda,
teto de gasto) fica atrás de **Ajustes**, fechado por padrão e escrito sem
jargão: `min_score` virou "quão exigente ser", `vertical_facetrack` virou
"vertical com zoom no rosto", `--dry-run` sumiu da tela. A tradução mora toda em
`web/src/lib/format.ts`.

Desenvolvendo o front, rode os dois processos (o Vite faz proxy de `/api`):

```bash
clip serve                    # API em :8765
cd web && npm run dev         # UI em :5173 com hot reload
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
lugar". Passado esse tempo, a API devolve o job como erro retriável
(`stale: true`) com **Retomar de onde parou**, que reaproveita todo o cache em
`work/`. Nada de spinner eterno.

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

## Enquadramento

O que sai de cada formato, e por quê.

| Formato | Enquadramento |
|---------|---------------|
| `vertical_facetrack` | Recorte 9:16 que **segue quem fala**, com um comando de crop por quadro. Em plano aberto (3+ pessoas, ou rosto pequeno na mesa) troca sozinho para um recorte 4:5 mais largo com fundo desfocado — que continua acompanhando a conversa, só que sem decepar ninguém na ponta. |
| `vertical_center` | Recorte central fixo **preenchendo a tela**. É o maior rosto possível sem tracking. |
| `horizontal_16x9` | Corte limpo, sem tracking. Nunca amplia além do que a fonte tem, e fonte fora de 16:9 (4:3, vertical, captura de tela) ganha fundo desfocado em vez de ter as laterais decepadas. |

Detalhes que definem a qualidade percebida:

- **A resolução da fonte manda.** O 9:16 recorta `altura x 9/16` da fonte e amplia até 1080px de largura: de um 1080p isso é 1,8x; de um 360p, 5,3x. O job avisa no resumo quando a fonte é pequena demais para o vertical sair nítido.
- **O crop anda por quadro.** A detecção roda a ~12 Hz, mas o comando de posição é emitido na taxa do vídeo (até 60 fps), interpolado. Um comando por amostra fazia cada posição segurar por 3 a 5 quadros: o salto máximo entre quadros consecutivos caiu de 20 px para 4 px.
- **Troca de câmera é salto, não deslize.** A suavização mede a diferença entre quadros e, num corte de plano, reinicia em vez de aplicar o limite de velocidade — senão o enquadramento atravessa o quadro novo devagar, mostrando a parede por um segundo antes de achar o rosto.
- **Quem fala manda no crop, quando dá para saber.** Se a diarização devolver rótulos de falante, a timeline vira entrada do tracking: aprendemos em que ponto da tela cada falante costuma estar (a diarização diz *quem* e *quando*, nunca *onde*) e o crop passa a seguir quem está falando, não o rosto maior. Sem diarização, o desempate entre dois rostos usa quanto a região da boca mudou — medida grosseira, então só entra com 2+ rostos e quando um está claramente mais ativo. Com um rosto em cena, nada disso muda o resultado.
- **A detecção decodifica em sequência.** Um `seek` por amostra obriga o decoder a voltar ao keyframe anterior toda vez; ler em ordem e processar 1 quadro a cada N deixou a detecção ~2,8x mais rápida. O quadro ainda é reduzido para 640px antes do MediaPipe — o detector trabalha em coordenadas normalizadas, então resolução extra ali é só CPU.

## Design

`PRODUCT.md` guarda o contexto estratégico (quem usa, em que situação, o que a
interface não pode parecer) e `DESIGN.md` o sistema visual (cor, tipo, layout,
movimento). Duas decisões de produto que explicam a forma da tela:

**Duas velocidades, dois layouts.** O job leva 20 a 30 minutos e a aba fica em
segundo plano; depois vêm 5 a 15 cortes para triar em poucos minutos. São usos
opostos. *Esperando*, a tela é grande e quase estática — o percentual em corpo
48, uma frase do que está acontecendo, e os cortes aparecendo à medida que
ficam prontos. *Escolhendo*, ela é uma bancada densa que responde ao teclado:
`←` `→` para andar, `Enter` para abrir, `G`/`R` para julgar, `Esc` para voltar.

**A miniatura é vertical.** O que se publica é o 9:16; julgar o corte por um
quadro 16:9 é olhar para um enquadramento que não vai ao ar — some justamente
o que o face tracking fez. O `poster_9x16.jpg` é extraído junto com o render,
não na primeira abertura da grade (senão os cards ficam pretos enquanto cinco
ffmpeg rodam).

Movimento corresponde a fato, nunca a montagem: só o corte que **acabou** de
ficar pronto anima a entrada (a lista é reconstruída a cada 2s — animar tudo
que renderiza vira um piscar contínuo), passar o mouse na miniatura avança o
vídeo em vez de dar zoom no card, e a nota conta de zero ao chegar porque a
nota é o veredito. `prefers-reduced-motion` troca tudo por transição
instantânea, e o estado final nunca depende de a animação ter rodado.

## Saída organizada para publicar

A pasta por corte (`out/<score>_<slug>/`) continua sendo a fonte da verdade —
é onde vivem o `meta.json`, as legendas e o que a interface lê. No fim do job,
os vídeos também aparecem agrupados por formato:

```
out/verticais/     75_conteudo-de-moto_rosto.mp4    <- 9:16 com face tracking
                   75_conteudo-de-moto_fixo.mp4     <- 9:16 enquadramento fixo
out/horizontais/   75_conteudo-de-moto.mp4          <- 16:9
```

São **hard links**, não cópias: o arquivo aparece nos dois lugares ocupando um
espaço só. Um job de 5 cortes passa de 240MB, e copiar dobraria isso.

## Desempenho

Alvo: MacBook Pro i5 de 4 núcleos, sem GPU útil. Onde o tempo vai, num job real
de 5 cortes a partir de um podcast de 3,5h: download 23%, transcrição 22%,
**render 49%**, resto 6%.

O que foi medido nesta máquina, e o que a medição derrubou:

- **A taxa de quadros é o maior lever do render.** A fonte vinha em 60fps e saía
  em 60fps por inércia. Em A/B alternado (justo mesmo com o notebook
  esquentando), limitar a saída a 30fps tirou **38%** do tempo dos três
  formatos. `CLIP_OUTPUT_FPS` sobe de volta para 60 se o corte pedir.
- **Aceleração por hardware não ajuda aqui.** `h264_videotoolbox` existe neste
  i5, mas ficou *mais lento* que o x264 (8,2s contra 6,0s) e gerou arquivo 7x
  maior. E `-hwaccel videotoolbox` no decode foi **4x mais lento** que software:
  o custo de trazer cada quadro de volta para a memória, onde os filtros
  precisam dele, supera o ganho.
- **O codec da fonte quase não importa para o decode.** O medo do AV1 em
  software não se confirmou: o dav1d fez 90s de 1080p60 em 5,5s contra 6,4s do
  H.264. Como o arquivo AV1 é 45% menor, ele é a escolha melhor — economiza
  download sem custar render.
- **Preset do x264 não vale mexer.** `superfast` é 15% mais rápido mas gera
  arquivo 2,2x maior (upload mais lento, e o SSIM mal muda); `faster` é 4x mais
  lento. `veryfast -crf 20` fica.
- **Dois ffmpeg em paralelo é o ponto ótimo.** Serial leva 78,6s para os três
  formatos de um corte, dois em paralelo 62,8s, três em paralelo 63,0s — o
  terceiro não cabe em 4 núcleos.
- **`sendcmd` custa caro e escala com o número de comandos.** Metade deles era
  `crop y`, que nunca muda (a altura do recorte é sempre a da fonte). Trocar o
  `sendcmd` por uma expressão de crop foi pior: o ffmpeg reavalia a expressão
  por quadro e uma expressão longa nem compila.
- **Blur em resolução cheia é desperdício.** O fundo desfocado agora é
  produzido a 1/6 da resolução e ampliado de volta — visualmente igual, ~1/36
  do trabalho.

### Ainda na mesa

Download e transcrição somam 45% do job e são espera de rede, não CPU. O maior
ganho restante é **baixar o áudio primeiro e transcrever enquanto o vídeo
baixa** — esconderia os ~6 min de transcrição atrás do download. Exige
reorganizar o começo do pipeline (progresso, cancelamento, `resume`), então
ficou de fora desta passada.

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

## Armadilhas já pagas

Coisas que quebraram de um jeito silencioso e agora têm teste ou comentário
segurando. Antes de "simplificar" algum destes pontos, leia o porquê.

- **Pontuação nas palavras do STT.** O endpoint devolve `segments[].text`
  pontuado e `words[]` sem nenhuma pontuação. Como toda a lógica de fronteira
  pergunta "esta palavra termina a frase?", sem reancorar a pontuação
  (`transcribe.attach_punctuation`) o `context_complete` era **sempre** falso,
  todo corte levava o teto de score de trecho truncado (45) e nada passava do
  limiar de 60. O pipeline terminava "com sucesso" entregando só reprovados.
- **Palavra em dois segmentos.** A fatia por segmento usava folgas que se
  sobrepunham: 7% das palavras de um podcast de 2h apareciam duas vezes, e
  vazavam repetidas no excerpt e na legenda ("direitinho Ele Ele era"). Agora
  cada palavra pertence a um segmento só (`_assign_words_to_segments`).
- **48 kHz obrigatório no áudio.** O filtro `loudnorm` reamostra internamente
  para 192 kHz; sem `-ar` explícito o AAC saía em **96 kHz**, que o ffmpeg lê
  numa boa mas nenhum navegador decodifica — o `<video>` trava sem imagem, sem
  som e sem mensagem de erro. `audio.AUDIO_ENCODE_ARGS` é o único lugar que
  define isso, e `tests/test_render.py` trava a taxa.
- **`response_format` não é universal.** Vários modelos da OpenRouter recusam
  `{"type": "json_object"}`. `chat_json` tenta sem ele no retry e
  `parse_json_response` aceita JSON dentro de cerca ```json ou depois de uma
  frase de introdução — antes, escolher Claude ou Llama num papel de texto fazia
  toda chamada falhar e o pipeline cair calado no fallback.
- **`player_client` do YouTube é do yt-dlp, não nosso.** Fixar `["web","ios","mweb"]` parecia inofensivo e congelou o projeto num conjunto que hoje devolve **só o formato 18 (360p progressivo)**: todo corte passou a sair de 360p, com o 9:16 recortando 202x360 para ampliar 5x. O padrão do yt-dlp é mantido upstream e entrega os formatos adaptativos até 1080p. `CLIP_YTDLP_PLAYER_CLIENT` existe como escape, e deve ficar vazio.
- **"Repetiu muito" não é alucinação.** O Whisper inventa boilerplate em cima de silêncio (51 segmentos de `www.opusdei.tp` num podcast, um deles ancorando o começo de um corte). Mas num podcast de rap o refrão repete, e `"Tá ligado?"` apareceu 30 vezes por ser bordão real de quem falava — nem o ritmo de fala separa os dois casos. O filtro só derruba o que **também** casa com padrão de URL ou crédito de legenda.
- **Estender o corte cresce pelo fim.** O modelo escolheu aquele início por um motivo. A versão anterior puxava o começo para trás por uma fração fixa da diferença e abria o corte no meio do assunto anterior; agora só o fim cresce, parando em fim de frase, e o começo só recua se o fim não bastar.
- **Fallback de copy é sintoma, não estilo.** Quando o modelo de textos falha, o
  corte ainda sai com título de template, mas agora `meta.json` registra
  `copy_source: "fallback"`, o job ganha uma nota no resumo e a tela avisa. Ficar
  em silêncio fazia todo corte sair com o mesmo título genérico sem ninguém
  entender por quê.

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

Alvo: MacBook Pro Intel i5 16GB; ffmpeg + yt-dlp + MediaPipe locais; STT/LLM/vision no OpenRouter.
