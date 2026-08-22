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
cp .env.example .env          # preencha OPENROUTER_API_KEY=
```

Sem MediaPipe o `vertical_facetrack` não é gerado (o job avisa e segue com
`vertical_center` + `horizontal_16x9`).

## Interface web

```bash
cd web && npm install && npm run build && cd ..
clip serve                    # http://127.0.0.1:8765
```

Desenvolvendo o front, rode os dois processos (o Vite faz proxy de `/api`):

```bash
clip serve                    # API em :8765
cd web && npm run dev         # UI em :5173 com hot reload
```

A interface é um app React + Vite (`web/`) que consome o mesmo payload de
progresso da CLI. Com ela você:

- cola a URL e escolhe quantidade (**auto** / **+50%** / **fixo N**), limiar de
  score, formatos, legendas e plataformas;
- estima o custo antes de gastar (**dry-run**) e trava um **orçamento** em USD;
- acompanha o job ao vivo: percentual global, estágio atual, **minutos
  restantes**, tempo de cada estágio e status de render por corte (quais
  formatos já saíram, qual está rodando, qual teve o 9:16 descartado);
- pré-visualiza cada corte nos três formatos, com breakdown do score, janelas
  9:16/16:9 e motivo do corte;
- copia títulos, descrições e hashtags de YouTube Shorts, YouTube 16:9 e TikTok;
- baixa os `.mp4`, `.srt` e `.ass`;
- vota **bom/ruim** por corte (vai para `work/feedback.jsonl` e volta como
  few-shot nos próximos prompts);
- pede **mais cortes** ou **refaz com N** reaproveitando o cache do job;
- quando um estágio falha, vê a dica em PT-BR e um botão **Tentar de novo** —
  a tela nunca fica girando para sempre (o SSE cai para polling sozinho).

Jobs criados na CLI aparecem na UI e vice-versa: o estado vive em
`work/<job_id>/status.json`.

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

### Payload de progresso

CLI, API e UI consomem exatamente o mesmo objeto:

```json
{
  "stage": "render",
  "stage_label": "Renderizando cortes",
  "percent": 83.0,
  "stage_percent": 57.0,
  "eta_seconds": 96,
  "eta_text": "~1.5 min restantes",
  "message": "Renderizando… 4/7 arquivos",
  "clips_done": 1,
  "clips_total": 3,
  "clips": [{ "slug": "...", "score": 88, "status": "running",
              "formats": {"horizontal_16x9": "done"}, "vertical_skipped": null }],
  "stages": [{ "name": "download", "status": "done", "elapsed_seconds": 42.1 }],
  "status": "running",
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
| `GET` | `/api/health` | ffmpeg, yt-dlp, MediaPipe, chave e modelos |
| `GET` | `/api/config` | regras do produto (teto de 90s, padding, faixas de N) |
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
  sub-janela alinhada a frase que caiba no teto; só quando não existe nenhuma é
  que exporta só `horizontal_16x9` com `vertical_skipped` no `meta.json`.
- 16:9 tem duração livre, decidida pela IA.
- Corte truncado não é publicável: contexto aberto tem teto de score 45 e `arco`
  no máximo 6, independentemente da nota que o modelo deu.
- `--more`/`--count` nunca inventam clip fraco: qualidade > quantidade.
- Face tracking (MediaPipe) roda só no `vertical_facetrack`, nunca no
  `vertical_center`/`horizontal_16x9`.
- Todas as chamadas de IA (STT, candidatos, score/vision, títulos) passam pela
  OpenRouter (`OPENROUTER_API_KEY`).

## Eficiência (alvo: MacBook Pro i5 16GB)

- `work/<job_id>/` guarda vídeo, áudio, transcrição, candidatos, frames e
  diarização: `resume` não re-baixa, não re-transcreve e não re-extrai frames.
- Chamadas de rede (STT, score, títulos) rodam em paralelo limitado
  (`CLIP_NETWORK_WORKERS`, default 3); render e face tracking usam um pool
  menor (`CLIP_RENDER_WORKERS`, default 2) porque ffmpeg e MediaPipe competem
  por CPU/RAM e subir demais só faz a máquina entrar em swap.
- Vision roda **só** nos candidatos, com 3 frames reduzidos a 512px — o scorer
  precisa enxergar enquadramento e reação, não 720p.
- `--dry-run` e `--budget` decidem antes do passo caro.

## Testes

```bash
pytest                 # ou: clip test
cd web && npm run build   # typecheck do front (tsc -b) + bundle
```

Os testes usam fixtures em `tests/fixtures/` (vídeo sintético + transcrição
PT-BR mockada) e mockam as chamadas de IA — não requerem rede nem
`OPENROUTER_API_KEY` real. `tests/test_server_clips.py` cobre os endpoints que a
UI consome (listagem de cortes, `Range` no preview, download, thumbnail e
feedback) e `tests/test_server.py` verifica que a UI lê exatamente os campos que
o payload de progresso promete.

Alvo: MacBook Pro Intel i5 16GB; ffmpeg + yt-dlp + MediaPipe locais; STT/LLM/vision no OpenRouter.
