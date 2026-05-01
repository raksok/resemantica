from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from resemantica.llm.prompts import render_named_sections

GenerationHook = Callable[[str, str], str]


@dataclass(slots=True)
class LLMClient:
    base_url: str
    timeout_seconds: int
    max_retries: int = 2
    generation_hook: GenerationHook | None = None
    _openai_client: Any | None = field(default=None, init=False, repr=False)
    openai_request_count: int = field(default=0, init=False)

    def generate_text(self, *, model_name: str, prompt: str) -> str:
        if self.generation_hook is not None:
            return self.generation_hook(model_name, prompt)

        client = self._get_openai_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                self.openai_request_count += 1
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

    def _get_openai_client(self) -> Any:
        if self._openai_client is None:
            self._openai_client = self._build_openai_client()
        return self._openai_client

    def translate_glossary_candidate(
        self,
        *,
        model_name: str,
        prompt_template: str,
        source_term: str,
        category: str,
        evidence_snippet: str,
    ) -> str:
        prompt = render_named_sections(
            prompt_template,
            sections={
                "SOURCE_TERM": source_term,
                "CATEGORY": category,
                "EVIDENCE_SNIPPET": evidence_snippet,
            },
        )
        return self.generate_text(model_name=model_name, prompt=prompt).strip()

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
