# Clip MVP — Spec

Ferramenta local de cortes automáticos a partir de link (YouTube / Twitch / etc.), focada em **YouTube** (Shorts + 16:9) e **TikTok**.

**Hardware alvo:** MacBook Pro 2020, Intel i5, 16GB RAM  
**IA:** tudo via **OpenRouter** (STT + LLM + vision)  
**Local:** download, face tracking, corte, legendas burn-in (`yt-dlp`, `ffmpeg`, MediaPipe)

---

## 1. Objetivo do MVP

Dado um link de vídeo longo:

1. Transcrever (PT-BR)
2. A IA decidir **quais** e **quantos** trechos valem como corte, **sempre fechando o contexto** da conversa
3. Dar score de viralização
4. Exportar por corte:
   - `9:16` com face tracking
   - `9:16` center crop (sem face tracking)
   - `16:9` trim limpo (sem face tracking)
5. Gerar legendas + títulos/hashtags/captions para YouTube e TikTok

**Fora do MVP:** upload automático, app mobile, B-roll, multi-usuário, SaaS, white-label.

---

## 2. Contexto da conversa + duração dos cortes

### Integridade de contexto (obrigatório)

O produto gera **vídeos curtos que fazem sentido sozinhos**. A IA **não pode cortar no meio** de uma fala, resposta, piada ou raciocínio.

Regras para `start` / `end`:

1. Começar em fronteira natural (início de pergunta, setup, mudança de assunto) — nunca no meio de uma frase.
2. Terminar só quando o **contexto estiver fechado** (punchline, resposta completa, conclusão do pensamento).
3. Se o momento forte for curto, **estender** o fim (e se preciso o início) até o bloco conversacional fechar — mesmo que o score “puro” do highlight seja menor.
4. Preferir um corte um pouco mais longo e completo a um corte “viral” truncado.
5. Validação pós-LLM (determinística): preferir **timestamps por palavra** do STT quando disponíveis; senão, limites de segmento. Nunca cortar no meio de uma palavra. Aplicar folga de **200–400ms** antes do `start` e depois do `end`. Se o texto terminar no meio de frase, expandir até o próximo fim de segmento/palavra com pontuação.

Isso vale para **todos** os formatos derivados do mesmo momento (9:16 face, 9:16 center, 16:9).

### Duração por formato

O LLM propõe um **intervalo canônico** `(start, end)` com contexto fechado. Na renderização:

| Formato | Duração | Regra |
|---------|---------|--------|
| `vertical_facetrack` (9:16) | **máx. 1:30** (90s) | Se o contexto fechado passar de 90s → **não** truncar no meio; ou (a) encolher só se ainda houver contexto completo numa janela ≤90s, ou (b) **descartar** esse vertical / não exportar 9:16 desse momento. Nunca cortar a frase no 1:30. |
| `vertical_center` (9:16) | **máx. 1:30** | Mesma regra do facetrack. |
| `horizontal_16x9` | **sem teto fixo de 90s** | A IA escolhe a duração (ex. ~45s–4 min típico; pode mais se o arco precisar). Deve fechar o contexto. Ideal para YouTube “corte” / highlight mais longo. |

**Alvos sugeridos (não rígidos):**

- 9:16: sweet spot **20–60s**, duro em **≤90s**
- 16:9: sweet spot **45s–3 min**, IA decide; priorizar arco completo

Um mesmo “momento” pode gerar:

- 9:16 com janela ≤90s (se o contexto couber), **e**
- 16:9 com janela maior (mesmo núcleo, mais setup/reação), desde que ambos fechem contexto.

Se o único contexto válido tiver **>90s**, exportar **só** o `horizontal_16x9` e registrar no `meta.json`: `"vertical_skipped": "context_exceeds_90s"`.

---

## 3. Quantidade de cortes (dinâmica)

### Comportamento padrão (`auto`)

A IA escolhe N com base em:

- duração do vídeo-fonte
- densidade de momentos fortes na transcrição
- diversidade (não repetir o mesmo gancho)
- piso e teto de segurança

**Heurística sugerida (o LLM pode ajustar dentro da faixa):**

| Duração fonte | Faixa alvo de cortes finais |
|---------------|-----------------------------|
| < 10 min      | 2–4                         |
| 10–30 min     | 3–6                         |
| 30–90 min     | 5–10                        |
| > 90 min      | 8–15                        |

Fluxo interno:

1. **Candidatos amplos:** LLM gera ~2–3× a faixa alvo, cada um com contexto **fechado** e propostas de janela `9:16` (≤90s) e `16:9` (duração livre)
2. **Score:** vision + texto ranqueia todos (penalizar trechos truncados / sem punch completo)
3. **Deduplicar:** se dois candidatos têm overlap temporal >50% ou a mesma punchline/ideia, manter só o de maior score
4. **Corte automático:** fica só quem passa no **limiar mínimo de score** (default `60`) e respeita o teto da faixa
5. Se poucos passarem do limiar, entrega menos (qualidade > quantidade)
6. Resposta / log: `selected=7, candidates=18, deduped=3, vertical_ok=6, vertical_skipped=1, reason=...`

### Override do usuário

```bash
clip "URL"                 # auto (default)
clip "URL" --more          # pede ~+50% vs. o que o auto escolheria (ainda com limiar)
clip "URL" --count 12      # força até 12 (desde que passem do limiar; avisa se faltar qualidade)
clip "URL" --min-score 50  # afrouxa limiar
clip "URL" --max-score-only 80  # só clips >= 80
```

`--more` e `--count` **não** inventam clip ruim: se não houver momento, o job explica e entrega o que passou.

Re-run barato (sem baixar de novo):

```bash
clip resume <job_id> --count 12
clip resume <job_id> --more
```

Usa transcrição + candidatos já em `work/<job_id>/`.

---

## 4. Stack

| Camada | Tech |
|--------|------|
| Linguagem | Python 3.11+ |
| CLI | `typer` |
| Download | `yt-dlp` |
| A/V | `ffmpeg`, `ffprobe` |
| Face track | `mediapipe`, `opencv-python`, `numpy` |
| HTTP / OpenRouter | `httpx` ou SDK OpenAI com `base_url=https://openrouter.ai/api/v1` |
| Config | `.env` → `OPENROUTER_API_KEY` |

### Modelos OpenRouter (slugs a confirmar no catálogo na hora do build)

| Papel | Sugestão | Notas |
|-------|----------|--------|
| STT | `openai/whisper-1` ou `openai/whisper-large-v3` | `language=pt`, `response_format=verbose_json` |
| Candidatos | modelo texto barato/rápido (ex. Gemini Flash class) | JSON estruturado |
| Score | modelo **vision** (texto + 3 frames) | breakdown 0–100 |

---

## 5. Estrutura do projeto

```
clip-mvp/
  SPEC.md
  .env.example
  requirements.txt
  src/clip_mvp/
    cli.py
    download.py
    transcribe.py
    candidates.py      # inclui decisão de N
    score.py
    face_track.py
    render.py
    meta.py            # títulos, hashtags, captions YT/TikTok
    dedupe.py
    budget.py          # dry-run / --budget
    feedback.py        # clip rate → few-shot
    audio.py           # loudnorm
    prompts/
      candidates_pt.md
      score_pt.md
      meta_pt.md
  tests/fixtures/      # vídeo BR + expected
  work/                # temporários por job + feedback.jsonl
  out/                 # entregáveis
```

---

## 6. Pipeline do job

```
URL
 → download (áudio + vídeo 720p)
 → transcribe (chunks ~10 min) → segments[]
 → candidates (auto N ou --count/--more; contexto fechado; janelas 9:16≤90s e 16:9 livre) → clips[]
 → score (texto + 3 frames; penaliza truncamento) → ranked[]
 → filter limiar + teto N → selected[]
 → para cada selected:
      se vertical cabe em ≤90s com contexto ok → face_track + render 9:16 face/center
      senão → skip vertical (meta.vertical_skipped)
      render 16:9 com duração escolhida pela IA
      loudnorm no áudio dos exports
      captions SRT (+ burn-in no vertical, safe area)
      meta.json (títulos, hashtags, captions, windows)
 → out/<score>_<slug>/
```

---

## 7. Exports por corte

```
out/87_hook-fulano/
  vertical_facetrack.mp4   # 9:16 + MediaPipe
  vertical_center.mp4      # 9:16 center, sem tracking
  horizontal_16x9.mp4      # 16:9 trim
  captions.srt
  captions.ass             # opcional (estilo TikTok)
  meta.json
```

### `meta.json` (exemplo)

```json
{
  "source_url": "https://youtube.com/watch?v=...",
  "context_complete": true,
  "windows": {
    "vertical_9x16": { "start": 612.4, "end": 668.0, "duration_s": 55.6 },
    "horizontal_16x9": { "start": 598.0, "end": 702.5, "duration_s": 104.5 }
  },
  "vertical_skipped": null,
  "score": 87,
  "breakdown": {
    "hook": 22,
    "emocao": 21,
    "citavel": 23,
    "arco": 21
  },
  "reason": "Pergunta + resposta completa; punchline nos segundos finais",
  "selection": {
    "mode": "auto",
    "candidates": 18,
    "selected": 7,
    "min_score": 60
  },
  "youtube": {
    "shorts_title": "...",
    "description": "...",
    "tags": ["...", "..."],
    "hashtags": ["#Shorts", "#..."]
  },
  "tiktok": {
    "caption": "...",
    "hashtags": ["#fyp", "#...", "..."]
  }
}
```

---

## 8. Score de viralização

Critérios (soma 100):

- **hook** (0–25) — primeiros ~3s
- **emocao** (0–25) — humor, tensão, surpresa
- **citavel** (0–25) — vira meme/corte sozinho
- **arco** (0–25) — setup → punch **completo** (contexto fechado)

**Penalidade dura:** trecho que começa/termina no meio da fala → score baixo ou rejeição, mesmo com momento “forte” no meio.

Entrada do scorer: trecho da transcrição + 3 frames (início / meio / fim).  
Saída: score, breakdown, reason curta em PT-BR + flag `context_complete`.

---

## 9. Face tracking (só `vertical_facetrack`)

- Rodar **apenas** nos trechos selected (não no vídeo inteiro)
- MediaPipe Face Detection ~8–12 fps
- Suavização EMA + limite de velocidade do crop
- Sem rosto <0,5s: segurar último centro; >2s: centro do frame
- `vertical_center` e `horizontal_16x9` **sem** face tracking

### Falantes (2+ pessoas)

- **Diarização** via OpenRouter/API de áudio (quando disponível) ou modelo STT com speaker labels → timeline `speaker_id` por intervalo
- Mapear `speaker_id` → rosto (maior overlap temporal + posição); na troca de falante, crop segue quem está falando (crossfade curto)
- Fallback se diarização falhar: maior atividade de boca/movimento (proxy), como hoje

---

## 10. Legendas e texto social

- SRT a partir dos timestamps do Whisper (recorte no intervalo do clip); preferir alinhamento palavra-a-palavra
- Burn-in grande no 9:16 (TikTok/Shorts); 16:9 com SRT sidecar (e burn-in opcional menor)
- **Safe area 9:16:** manter legendas fora da UI de TikTok/Shorts — evitar ~20% inferior e margens laterais apertadas; centralizar bloco de texto na zona segura central
- OpenRouter gera, em PT-BR:
  - TikTok: caption + 4–6 hashtags (nicho + alcance, sem spam)
  - YouTube Shorts: título, descrição curta, tags/hashtags
  - YouTube 16:9: título + descrição um pouco mais SEO

---

## 11. CLI

```bash
clip "URL"
clip "URL" --more
clip "URL" --count 12
clip "URL" --min-score 55
clip "URL" --formats face,9x16,16x9
clip "URL" --captions burn|sidecar|both
clip "URL" --platforms yt,tiktok
clip "URL" --dry-run              # estima custo OpenRouter sem vision/render completo
clip "URL" --budget 2.00          # aborta ou reduz candidatos se estimar acima (USD)
clip resume <job_id> --more
clip resume <job_id> --count 12
clip rate <job_id> <clip_slug> good|bad [--note "..."]
```

Defaults: `--formats face,9x16,16x9`, `--captions both`, `--platforms yt,tiktok`, seleção `auto`.

---

## 12. Ordem de build

1. CLI + download + corte ffmpeg manual por timestamp + **loudnorm**  
2. Whisper (`verbose_json` / word timestamps) + dump da transcrição  
3. Candidatos + seleção auto de N + `--more` / `--count` + **dedupe**  
4. Score + limiar + **`--dry-run` / `--budget`**  
5. Render 9:16 center + 16:9 + SRT com **safe area**  
6. Face track → `vertical_facetrack`  
7. Diarização → speaker↔rosto (pode logo após o face track básico)  
8. `meta.json` (títulos/hashtags YT + TikTok)  
9. `clip rate` + few-shot nos prompts  
10. Fixture de teste BR + polish de prompts PT-BR  

---

## 13. Critérios de “MVP pronto”

- [ ] Um link YouTube gera pasta `out/` com exports + SRT + `meta.json`
- [ ] Cortes não truncam frase/contexto; fronteira por **palavra** + folga 200–400ms
- [ ] 9:16 sempre ≤ 90s; se contexto >90s, só 16:9 (ou skip vertical)
- [ ] 16:9 com duração escolhida pela IA (pode >90s)
- [ ] Sem flags, N de cortes varia com o vídeo (não fixo em 5)
- [ ] Dedupe de overlap/punchline duplicada
- [ ] Áudio exportado com loudness normalizado
- [ ] Legendas 9:16 respeitam safe area TikTok/Shorts
- [ ] `--dry-run` e `--budget` estimam/limitam custo OpenRouter
- [ ] `--more` e `--count` funcionam (com `resume` sem re-download)
- [ ] `clip rate good|bad` grava feedback e influencia prompts seguintes
- [ ] Diarização (ou fallback documentado) para 2+ falantes no face track
- [ ] Existe fixture de teste BR com expectativas mínimas de timestamps
- [ ] Score e reason no `meta.json` e no nome da pasta
- [ ] Face track só no vertical_facetrack; center e 16:9 sem tracking
- [ ] Hashtags/títulos distintos para TikTok vs YouTube
- [ ] Roda de ponta a ponta no Mac i5 16GB sem modelo local pesado de LLM

---

## 14. Melhorias obrigatórias (qualidade)

Estas oito regras fazem parte da spec do produto (não são “ideias futuras” soltas).

### 14.1 Fronteira no nível da palavra
- Usar word timestamps do STT sempre que o provider/OpenRouter expor
- Proibido cortar no meio de palavra
- Padding **200–400ms** em `start`/`end` após snapping
- Se só houver segmentos, snappoints + expansão até fim de frase

### 14.2 Normalizar áudio
- Passar exports finais (e de preferência o áudio de trabalho) por **loudnorm** (`ffmpeg`)
- Alvo típico: loudness de diálogo consistente entre falantes/cortes
- Evitar pico estourado após o crop

### 14.3 Deduplicar momentos
- Overlap temporal **>50%** → manter maior score
- Mesma punchline/ideia (LLM ou similaridade de texto do trecho) → manter maior score
- Logar quantos foram removidos por dedupe

### 14.4 Orçamento de custo OpenRouter
- Antes do score com vision: estimar minutos STT + nº de candidatos × custo vision
- `clip --dry-run`: imprime estimativa e para antes do passo caro
- `clip --budget <usd>`: reduz nº de candidatos ou aborta com mensagem clara se estourar
- Cache agressivo em `work/<job_id>/` (transcrição, frames, scores) para `resume` barato

### 14.5 Safe area de legenda (9:16)
- Zona segura central; **evitar ~20% inferior** (UI TikTok/Shorts) e laterais apertadas
- Burn-in e preview devem respeitar a mesma máscara
- 16:9 pode usar posicionamento mais clássico (terço inferior sem a mesma restrição de UI mobile)

### 14.6 Dois falantes de verdade
- Diarização → timeline de speakers
- Ligar speaker ativo ao rosto no frame; crop acompanha quem fala
- Fallback: atividade facial, se diarização indisponível/ falhar
- Documentar no `meta.json` se usou `diarization` ou `activity_proxy`

### 14.7 Loop de feedback
- `clip rate <job_id> <clip_slug> good|bad`
- Persistir em `work/feedback.jsonl` (slug, score, reason, veredicto, nota)
- Injetar N exemplos recentes good/bad como few-shot nos prompts de candidatos/score (PT-BR, nicho do usuário)
- Não treinar modelo local no MVP — só prompt + memória de feedback

### 14.8 Caso de teste fixo (fixture)
- Um vídeo/podcast BR curto versionado (URL fixa ou arquivo em `tests/fixtures/`)
- Arquivo `expected.md` / JSON com: nº mínimo de cortes com `context_complete`, pelo menos um 9:16 ≤90s, ausência de corte mid-word óbvio
- Comando `clip test` ou pytest que roda o pipeline (ou trechos mockados) e falha se regredir
- Usar a fixture sempre que mudar prompts de candidatos/score

---

## 15. Riscos / notas

- Chunks de áudio: respeitar limite de tamanho do endpoint STT do OpenRouter  
- Costo: vision no score é o item mais caro — só nos candidatos, não em todo o vídeo; usar `--budget`  
- Word timestamps / diarização: disponibilidade varia por modelo no OpenRouter — ter fallback na spec  
- ToS: uso de links de terceiros é responsabilidade do usuário  
- Qualidade PT-BR depende dos prompts + feedback loop (`clip rate`)  
- Disco no Mac 16GB/SSD: limpar `work/` antigo; preferir 720p  
