# clip-mvp

MVP local de cortes automáticos (YouTube Shorts / TikTok / 16:9) com IA via OpenRouter.

**Spec canônica:** [`SPEC.md`](./SPEC.md)

## Status

Implementação em andamento via Cursor cloud agents (loop build → review → improve).

## Quick start (quando o código existir)

```bash
cp .env.example .env   # OPENROUTER_API_KEY=
pip install -e .
clip "https://youtube.com/watch?v=..."
```

Alvo: MacBook Pro Intel i5 16GB; ffmpeg + yt-dlp + MediaPipe locais; STT/LLM/vision no OpenRouter.
