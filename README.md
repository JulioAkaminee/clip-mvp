# clip-mvp

MVP local de cortes automáticos (YouTube Shorts / TikTok / 16:9) com IA via OpenRouter.

**Spec canônica:** [`SPEC.md`](./SPEC.md)

## Status

Pipeline `core` implementado em `src/clip_mvp/` (download → transcrição →
candidatos → score → render → face track → diarização → meta.json →
feedback), seguindo a ordem de build da [SPEC §12](./SPEC.md#12-ordem-de-build).
Sem UI — outra squad cuida do front.

## Instalação

Requisitos: Python 3.11+, `ffmpeg`/`ffprobe` no PATH.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env   # preencha OPENROUTER_API_KEY=
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

# Roda a suíte de testes (fixtures BR)
clip test
```

`clip "URL"` é equivalente a `clip run "URL"` — o entrypoint reconhece se o
primeiro argumento é um subcomando (`run`, `resume`, `rate`, `cut`, `test`) ou
uma URL solta.

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
- 9:16 sempre ≤ 90s; se o contexto fechado só existir em janela maior, exporta
  só `horizontal_16x9` e registra `vertical_skipped` no `meta.json`.
- 16:9 tem duração livre, decidida pela IA.
- `--more`/`--count` nunca inventam clip fraco: qualidade > quantidade.
- Face tracking (MediaPipe) roda só no `vertical_facetrack`, nunca no
  `vertical_center`/`horizontal_16x9`.
- Todas as chamadas de IA (STT, candidatos, score/vision, títulos) passam pela
  OpenRouter (`OPENROUTER_API_KEY`).

## Testes

```bash
pytest
# ou
clip test
```

Os testes usam fixtures em `tests/fixtures/` (vídeo sintético + transcrição
PT-BR mockada) e mockam as chamadas de IA — não requerem rede nem
`OPENROUTER_API_KEY` real.

Alvo: MacBook Pro Intel i5 16GB; ffmpeg + yt-dlp + MediaPipe locais; STT/LLM/vision no OpenRouter.
