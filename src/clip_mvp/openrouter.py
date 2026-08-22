"""Cliente OpenRouter (STT, texto e vision) — SPEC §4.

Toda chamada de IA do pipeline passa por aqui, usando o SDK da OpenAI com
`base_url` apontando para a OpenRouter (conforme SPEC §4). Isolado num só
módulo para facilitar mock em testes (nenhum outro módulo importa `openai`
diretamente).
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
from typing import Any

from tenacity import retry, stop_after_attempt, wait_exponential

from .config import Settings


class OpenRouterClient:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._client = None

    @property
    def client(self):
        if self._client is None:
            from openai import OpenAI

            self._client = OpenAI(
                api_key=self.settings.require_api_key(),
                base_url=self.settings.openrouter_base_url,
            )
        return self._client

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    def transcribe(self, audio_path: Path, *, language: str = "pt") -> dict[str, Any]:
        """Chama o endpoint de transcrição (Whisper) pedindo verbose_json com
        timestamps por palavra, quando o provider suportar (SPEC §14.1)."""
        with open(audio_path, "rb") as f:
            resp = self.client.audio.transcriptions.create(
                model=self.settings.stt_model,
                file=f,
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["word", "segment"],
            )
        if hasattr(resp, "model_dump"):
            return resp.model_dump()
        if isinstance(resp, dict):
            return resp
        return json.loads(resp.json()) if hasattr(resp, "json") else dict(resp)

    @retry(wait=wait_exponential(multiplier=1, min=1, max=10), stop=stop_after_attempt(3))
    def chat_json(
        self,
        *,
        model: str,
        system: str,
        user: str,
        images_b64: list[str] | None = None,
        temperature: float = 0.4,
    ) -> dict[str, Any]:
        """Chat completion pedindo JSON estruturado, opcionalmente com imagens
        (usado no scorer de vision, SPEC §8)."""
        content: list[dict[str, Any]] = [{"type": "text", "text": user}]
        for img in images_b64 or []:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{img}"},
                }
            )

        resp = self.client.chat.completions.create(
            model=model,
            temperature=temperature,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
        )
        text = resp.choices[0].message.content
        return json.loads(text)


def image_to_b64(path: Path) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")
