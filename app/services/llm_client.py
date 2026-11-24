"""Provider-agnostic LLM client with a 100% free local Ollama implementation."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import Settings, get_settings
from app.core.exceptions import LLMGenerationError
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class LLMResponse:
    """Text response and latency/token telemetry from an LLM call."""

    content: str
    model: str
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMClient(Protocol):
    """Interface implemented by any LLM provider."""

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
    ) -> LLMResponse: ...


class OllamaLLMClient:
    """Calls a locally running Ollama server via its REST /api/chat endpoint."""

    def __init__(
        self,
        settings: Settings | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._http_client = http_client

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
    ) -> LLMResponse:
        url = f"{self.settings.ollama_base_url.rstrip('/')}/api/chat"
        payload = {
            "model": self.settings.llm_model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }

        start = time.perf_counter()
        try:
            if self._http_client is not None:
                response = self._http_client.post(url, json=payload)
            else:
                with httpx.Client(timeout=self.settings.llm_timeout_seconds) as client:
                    response = client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()
        except httpx.ConnectError as exc:
            raise LLMGenerationError(
                f"Cannot reach Ollama at {self.settings.ollama_base_url}. "
                "Ensure Ollama is installed and running (`ollama serve`)."
            ) from exc
        except (httpx.HTTPError, ValueError) as exc:
            raise LLMGenerationError(f"Ollama request failed: {exc}") from exc

        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        content = (data.get("message") or {}).get("content", "").strip()
        if not content:
            raise LLMGenerationError("Ollama returned an empty response.")

        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion_tokens = int(data.get("eval_count") or 0)

        logger.info(
            "LLM generation completed",
            extra={
                "extra_data": {
                    "model": self.settings.llm_model,
                    "latency_ms": elapsed_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                }
            },
        )
        return LLMResponse(
            content=content,
            model=self.settings.llm_model,
            latency_ms=elapsed_ms,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )