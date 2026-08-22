# clip-mvp

MVP local de cortes automáticos (YouTube Shorts / TikTok / 16:9) com IA via OpenRouter.

Cole o link de um vídeo longo. A IA transcreve em PT-BR, decide **quais** e **quantos** momentos
valem corte (sempre fechando o contexto da conversa), pontua o potencial de viralização e exporta
`9:16` com face tracking, `9:16` center, `16:9`, legendas e os textos de publicação para YouTube e
TikTok.

**Spec canônica:** [`SPEC.md`](./SPEC.md) · **Alvo:** MacBook Pro 2020 (Intel i5, 16GB)

---

## Requisitos

| Requisito | Como instalar (macOS) |
|-----------|------------------------|
| Python 3.11+ | `brew install python@3.12` |
| ffmpeg + ffprobe | `brew install ffmpeg` |
| Node 20+ (só para a UI) | `brew install node` |
| Chave OpenRouter | [openrouter.ai/keys](https://openrouter.ai/keys) |

## Instalação

```bash
git clone https://github.com/JulioAkaminee/clip-mvp && cd clip-mvp
cp .env.example .env          # cole sua OPENROUTER_API_KEY

python3 -m venv .venv && source .venv/bin/activate
pip install -e .              # núcleo (CLI + API)
pip install -e '.[facetrack]' # + MediaPipe/OpenCV para o vertical_facetrack
```

Sem `OPENROUTER_API_KEY` o app roda em **modo demo**: transcrição, candidatos, score e textos são
sintéticos (PT-BR, determinísticos), mas o download, o render, as legendas e os exports são reais.
Serve para conhecer a interface sem gastar crédito.

Sem MediaPipe o `vertical_facetrack` cai para center crop e isso fica registrado no `meta.json`
(`"face_track": "center_fallback"`).

## Rodando a UI web

```bash
cd web && npm install && npm run build && cd ..
clip serve                    # http://127.0.0.1:8000
```

Durante o desenvolvimento do front, rode os dois processos:

```bash
clip serve                    # API em :8000
cd web && npm run dev         # UI em :5173 com proxy /api → :8000
```

A interface permite:

- colar o link, escolher formatos, legendas, plataformas e limiar de score;
- deixar a quantidade no **auto** (a IA decide) ou usar **+50%** (`--more`) e **fixo** (`--count`);
- estimar o custo OpenRouter antes de gastar (**dry-run**) e travar um **orçamento** em USD;
- acompanhar o job ao vivo (SSE) etapa por etapa, com log e estatísticas de seleção;
- pré-visualizar cada corte nos três formatos, ler a transcrição e o breakdown do score;
- copiar títulos/descrições/hashtags de YouTube Shorts, YouTube 16:9 e TikTok;
- baixar os `.mp4`, o `.srt` e o `.ass`;
- avaliar o corte como **bom/ruim** — o veredicto volta como few-shot nos próximos prompts;
- pedir **mais cortes** ou **refazer com N** reaproveitando transcrição e scores em cache.

Jobs rodados na CLI aparecem na UI e vice-versa (o estado vive em `work/<job_id>/job.json`).

## CLI

```bash
clip "https://youtube.com/watch?v=..."        # auto: a IA escolhe N
clip "URL" --more                             # ~+50% cortes
clip "URL" --count 12                         # até 12 (só os que passarem do limiar)
clip "URL" --min-score 55                     # afrouxa o limiar (default 60)
clip "URL" --max-score-only 80                # só cortes >= 80
clip "URL" --formats face,9x16,16x9           # default
clip "URL" --captions burn|sidecar|both       # default both
clip "URL" --platforms yt,tiktok              # default
clip "URL" --dry-run                          # só estima o custo OpenRouter
clip "URL" --budget 2.00                      # reduz candidatos ou aborta acima de US$ 2
clip "URL" --demo                             # força o modo sem OpenRouter

clip resume <job_id> --more                   # sem re-baixar nem re-transcrever
clip resume <job_id> --count 12
clip rate <job_id> <clip_slug> good --note "abriu no lugar certo"
clip feedback                                 # últimos veredictos
clip serve                                    # API + UI
clip test                                     # fixture + pytest
```

`clip "URL"` também aceita caminho de arquivo local (`clip ~/Downloads/podcast.mp4`), útil para
testar sem depender de download.

## Saída

```
out/<job_id>/87_hook-fulano/
  vertical_facetrack.mp4   # 9:16 seguindo quem fala (MediaPipe + diarização quando disponível)
  vertical_center.mp4      # 9:16 center crop, sem tracking
  horizontal_16x9.mp4      # 16:9 trim limpo, duração escolhida pela IA
  captions.srt             # sidecar no intervalo canônico
  captions.ass             # burn-in estilo TikTok, respeitando a safe area
  meta.json                # score, breakdown, janelas, seleção, YT + TikTok
  poster.jpg
```

`work/<job_id>/` guarda a fonte, a transcrição, os scores e o estado do job — é o que faz o
`resume` ser barato. `work/feedback.jsonl` guarda os veredictos de `clip rate`.

## Regras de produto que o código garante

- **Nunca cortar no meio de fala ou palavra.** As janelas do LLM passam por validação
  determinística: snap para início/fim de frase por *word timestamps* (fallback em segmentos),
  expansão até a pontuação que fecha o contexto e folga de 200–400ms nas pontas.
- **9:16 no máximo 90s.** Se o contexto fechado não couber, a janela encolhe mantendo o fecho — e
  se ainda não couber, o vertical é descartado (`"vertical_skipped": "context_exceeds_90s"`) e só o
  16:9 é exportado. O 9:16 nunca é truncado no 1:30.
- **16:9 sem teto fixo.** A duração é escolhida pela IA e pode passar de 90s.
- **A IA escolhe a quantidade.** N varia com a duração da fonte, a densidade de momentos e a
  diversidade; `--more`/`--count` mexem no alvo mas nunca inventam corte ruim — se não houver
  momento acima do limiar, o job entrega menos e explica no log.
- **Dedupe.** Overlap temporal > 50% ou mesma punchline: fica o de maior score.
- **Áudio normalizado.** Todo export passa por `loudnorm` (I=-16, TP=-1.5, LRA=11).
- **Safe area da legenda.** No 9:16 o bloco de texto fica fora dos ~20% de baixo (UI do
  TikTok/Shorts) e das margens laterais apertadas.
- **Toda a IA no OpenRouter.** STT, candidatos, score (texto + 3 frames) e textos sociais. Nada de
  LLM local pesado; o Mac só roda `yt-dlp`, `ffmpeg` e MediaPipe.

## API

`clip serve` sobe a API local que a UI consome (docs interativas em `/docs`):

| Método | Rota | Para quê |
|--------|------|----------|
| `GET` | `/api/health` | ffmpeg, yt-dlp, MediaPipe, chave, modo demo |
| `GET` | `/api/config` | regras do produto (90s, pad, safe area, faixas de N) |
| `POST` | `/api/estimate` | dry-run de custo sem baixar nada |
| `POST` | `/api/jobs` | cria o job |
| `GET` | `/api/jobs` | lista jobs (inclui os da CLI) |
| `GET` | `/api/jobs/{id}` | estado completo do job |
| `GET` | `/api/jobs/{id}/events` | progresso ao vivo (SSE) |
| `POST` | `/api/jobs/{id}/cancel` | cancela |
| `POST` | `/api/jobs/{id}/resume` | `more` ou `count` reusando o cache |
| `DELETE` | `/api/jobs/{id}?files=true` | remove job (e opcionalmente os exports) |
| `POST` | `/api/jobs/{id}/clips/{slug}/rate` | feedback good/bad |
| `GET` | `/api/jobs/{id}/clips/{slug}/files/{nome}` | stream (com Range) e download |

## Testes

```bash
pytest                     # ou: clip test
pytest --fixture-video ~/Downloads/podcast_br.mp4
```

A suíte cobre as regras duras da SPEC: fronteira por palavra, folga de 200–400ms, teto de 90s do
9:16 (incluindo o descarte quando o contexto não fecha), faixas de N, dedupe, orçamento, safe area
das legendas e o contrato da API. `tests/fixtures/expected.json` descreve as expectativas mínimas
do teste de ponta a ponta e como gerar o vídeo da fixture.

## Variáveis de ambiente

```bash
OPENROUTER_API_KEY=            # obrigatória para a IA real
OPENROUTER_STT_MODEL=openai/whisper-1
OPENROUTER_CANDIDATE_MODEL=google/gemini-2.5-flash
OPENROUTER_SCORE_MODEL=google/gemini-2.5-flash
OPENROUTER_META_MODEL=google/gemini-2.5-flash
CLIP_MVP_DEMO=1                # força o modo demo
CLIP_MVP_HOME=/caminho         # onde ficam work/ e out/
```

Uso de links de terceiros é responsabilidade de quem roda a ferramenta.
