from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any, Callable


GenerationHook = Callable[[str, str], str]


@dataclass(slots=True)
class LLMClient:
    base_url: str
    timeout_seconds: int
    max_retries: int = 2
    generation_hook: GenerationHook | None = None

    def generate_text(self, *, model_name: str, prompt: str) -> str:
        if self.generation_hook is not None:
            return self.generation_hook(model_name, prompt)

        client = self._build_openai_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                response: Any = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                )
                content = response.choices[0].message.content
                return content if isinstance(content, str) else ""
            except Exception as exc:  # pragma: no cover - network/client failures
                last_error = exc
                if attempt >= self.max_retries:
                    break
                time.sleep(0.2)

        if last_error is None:  # pragma: no cover - defensive fallback
            raise RuntimeError("LLM generation failed with unknown error.")
        raise RuntimeError(f"LLM generation failed: {last_error}") from last_error

    def _build_openai_client(self) -> Any:
        try:
            from openai import OpenAI  # type: ignore
        except ImportError as exc:  # pragma: no cover - dependency/runtime concern
            raise RuntimeError(
                "openai package is required for runtime LLM calls. "
                "Install dependencies before running translate-chapter."
            ) from exc

        return OpenAI(
            base_url=self.base_url,
            api_key="not-required-for-local-router",
            timeout=self.timeout_seconds,
        )

