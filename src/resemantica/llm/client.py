from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from resemantica.llm.prompts import render_named_sections

GenerationHook = Callable[[str, str], str]
LLM_USAGE_PAYLOAD_FIELDS = (
    "llm_request_count",
    "llm_usage_tracked_count",
    "llm_cache_hit_count",
    "llm_prompt_tokens",
    "llm_completion_tokens",
    "llm_total_tokens",
)


@dataclass(slots=True)
class LLMUsageTotals:
    llm_request_count: int = 0
    llm_usage_tracked_count: int = 0
    llm_cache_hit_count: int = 0
    llm_prompt_tokens: int = 0
    llm_completion_tokens: int = 0
    llm_total_tokens: int = 0

    def copy(self) -> LLMUsageTotals:
        return LLMUsageTotals(**self.to_payload())

    def to_payload(self) -> dict[str, int]:
        return {
            "llm_request_count": self.llm_request_count,
            "llm_usage_tracked_count": self.llm_usage_tracked_count,
            "llm_cache_hit_count": self.llm_cache_hit_count,
            "llm_prompt_tokens": self.llm_prompt_tokens,
            "llm_completion_tokens": self.llm_completion_tokens,
            "llm_total_tokens": self.llm_total_tokens,
        }

    def delta(self, earlier: LLMUsageTotals) -> LLMUsageTotals:
        return LLMUsageTotals(
            llm_request_count=max(0, self.llm_request_count - earlier.llm_request_count),
            llm_usage_tracked_count=max(0, self.llm_usage_tracked_count - earlier.llm_usage_tracked_count),
            llm_cache_hit_count=max(0, self.llm_cache_hit_count - earlier.llm_cache_hit_count),
            llm_prompt_tokens=max(0, self.llm_prompt_tokens - earlier.llm_prompt_tokens),
            llm_completion_tokens=max(0, self.llm_completion_tokens - earlier.llm_completion_tokens),
            llm_total_tokens=max(0, self.llm_total_tokens - earlier.llm_total_tokens),
        )


def capture_usage_snapshot(client: object | None) -> LLMUsageTotals:
    if client is None:
        return LLMUsageTotals()
    snapshot = getattr(client, "snapshot_usage", None)
    if callable(snapshot):
        value = snapshot()
        if isinstance(value, LLMUsageTotals):
            return value.copy()
    return LLMUsageTotals()


def usage_payload_delta(client: object | None, before: LLMUsageTotals) -> dict[str, int]:
    after = capture_usage_snapshot(client)
    return after.delta(before).to_payload()


def record_cache_hit(client: object | None) -> None:
    callback = getattr(client, "record_cache_hit", None)
    if callable(callback):
        callback()


@dataclass(slots=True)
class LLMClient:
    base_url: str
    timeout_seconds: int
    max_retries: int = 2
    generation_hook: GenerationHook | None = None
    _openai_client: Any | None = field(default=None, init=False, repr=False)
    openai_request_count: int = field(default=0, init=False)
    _usage_totals: LLMUsageTotals = field(default_factory=LLMUsageTotals, init=False, repr=False)

    def generate_text(self, *, model_name: str, prompt: str) -> str:
        if self.generation_hook is not None:
            return self.generation_hook(model_name, prompt)

        client = self._get_openai_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                self.openai_request_count += 1
                self._usage_totals.llm_request_count += 1
                response: Any = client.chat.completions.create(
                    model=model_name,
                    messages=[{"role": "user", "content": prompt}],
                )
                self._record_response_usage(response)
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

    def snapshot_usage(self) -> LLMUsageTotals:
        return self._usage_totals.copy()

    def record_cache_hit(self) -> None:
        self._usage_totals.llm_cache_hit_count += 1

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

    def _record_response_usage(self, response: Any) -> None:
        usage = getattr(response, "usage", None)
        if usage is None and isinstance(response, dict):
            usage = response.get("usage")
        if usage is None:
            return

        prompt_tokens = self._usage_value(usage, "prompt_tokens")
        completion_tokens = self._usage_value(usage, "completion_tokens")
        total_tokens = self._usage_value(usage, "total_tokens")
        if prompt_tokens is None and completion_tokens is None and total_tokens is None:
            return

        self._usage_totals.llm_usage_tracked_count += 1
        if prompt_tokens is not None:
            self._usage_totals.llm_prompt_tokens += prompt_tokens
        if completion_tokens is not None:
            self._usage_totals.llm_completion_tokens += completion_tokens
        if total_tokens is not None:
            self._usage_totals.llm_total_tokens += total_tokens

    @staticmethod
    def _usage_value(usage: Any, key: str) -> int | None:
        value: Any
        if isinstance(usage, dict):
            value = usage.get(key)
        else:
            value = getattr(usage, key, None)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

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
