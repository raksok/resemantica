from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from loguru import logger

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
_MODEL_SEMAPHORE_LOCK = threading.Lock()
_MODEL_SEMAPHORES: dict[str, tuple[int, threading.BoundedSemaphore]] = {}


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
    max_concurrent_requests_per_model: int = 1
    throttle_groups: dict[str, Any] = field(default_factory=dict)
    generation_hook: GenerationHook | None = None
    _openai_client: Any | None = field(default=None, init=False, repr=False)
    openai_request_count: int = field(default=0, init=False)
    _usage_totals: LLMUsageTotals = field(default_factory=LLMUsageTotals, init=False, repr=False)

    def generate_text(self, *, model_name: str, prompt: str, max_tokens: int | None = None) -> str:
        if self.generation_hook is not None:
            return self.generation_hook(model_name, prompt)

        client = self._get_openai_client()
        last_error: Exception | None = None

        for attempt in range(self.max_retries + 1):
            throttle = _throttle_for_model(
                model_name,
                self.max_concurrent_requests_per_model,
                self.throttle_groups,
            )
            semaphore = _model_semaphore(
                throttle.key,
                throttle.limit,
            )
            semaphore.acquire()
            try:
                self.openai_request_count += 1
                self._usage_totals.llm_request_count += 1
                messages = [{"role": "user", "content": prompt}]
                if throttle.system_prompt:
                    messages.insert(0, {"role": "system", "content": throttle.system_prompt})
                request_kwargs: dict[str, Any] = {
                    "model": model_name,
                    "messages": messages,
                }
                if max_tokens is not None:
                    request_kwargs["max_tokens"] = max_tokens
                response: Any = client.chat.completions.create(**request_kwargs)
                self._record_response_usage(response)
                content = response.choices[0].message.content
                return content if isinstance(content, str) else ""
            except Exception as exc:  # pragma: no cover - network/client failures
                last_error = exc
                if attempt >= self.max_retries:
                    break
                logger.warning(
                    "LLM request failed; retrying (model={}, attempt={}, max_retries={}): {}",
                    model_name,
                    attempt + 1,
                    self.max_retries,
                    exc,
                )
                time.sleep(0.2)
            finally:
                semaphore.release()

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

    def concurrency_limit(self, model_name: str) -> int:
        """Return the effective request concurrency for a model."""
        return _throttle_for_model(
            model_name,
            self.max_concurrent_requests_per_model,
            self.throttle_groups,
        ).limit

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
        return _clean_glossary_translation_output(self.generate_text(model_name=model_name, prompt=prompt))

    def translate_glossary_fill_candidate(
        self,
        *,
        model_name: str,
        prompt_template: str,
        source_term: str,
        category: str,
        evidence_snippet: str,
        existing_alternatives: str,
    ) -> str:
        prompt = render_named_sections(
            prompt_template,
            sections={
                "SOURCE_TERM": source_term,
                "CATEGORY": category,
                "EVIDENCE_SNIPPET": evidence_snippet,
                "EXISTING_ALTERNATIVES": existing_alternatives,
            },
        )
        return _clean_glossary_translation_output(self.generate_text(model_name=model_name, prompt=prompt))

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
            from openai import OpenAI
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


def _model_semaphore(model_name: str, limit: int) -> threading.BoundedSemaphore:
    if limit < 1:
        raise ValueError("max_concurrent_requests_per_model must be >= 1.")
    with _MODEL_SEMAPHORE_LOCK:
        registered = _MODEL_SEMAPHORES.get(model_name)
        if registered is not None and registered[0] == limit:
            return registered[1]
        semaphore = threading.BoundedSemaphore(limit)
        _MODEL_SEMAPHORES[model_name] = (limit, semaphore)
        return semaphore


@dataclass(frozen=True, slots=True)
class _Throttle:
    key: str
    limit: int
    system_prompt: str = ""


def _throttle_for_model(
    model_name: str,
    default_limit: int,
    throttle_groups: dict[str, Any],
) -> _Throttle:
    for group_name, group in throttle_groups.items():
        model_names = (
            group.get("model_names", [])
            if isinstance(group, dict)
            else getattr(group, "model_names", [])
        )
        if model_name not in model_names:
            continue
        limit = (
            group.get("max_concurrent_requests", 1)
            if isinstance(group, dict)
            else getattr(group, "max_concurrent_requests", 1)
        )
        system_prompt = (
            group.get("system_prompt", "")
            if isinstance(group, dict)
            else getattr(group, "system_prompt", "")
        )
        if not isinstance(system_prompt, str):
            system_prompt = ""
        return _Throttle(f"group:{group_name}", int(limit), system_prompt)
    return _Throttle(f"model:{model_name}", default_limit)


def _clean_glossary_translation_output(output: str) -> str:
    translated = output.strip()
    # Strip common label prefixes that LLMs sometimes echo back
    translated = re.sub(
        r'^(Category|Translation|Term|Evidence|Output|Result|English)\s*:\s*',
        '',
        translated,
        flags=re.IGNORECASE | re.MULTILINE,
    ).strip()
    # Take last non-empty line (defense against chain-of-thought before answer)
    lines = [ln.strip() for ln in translated.splitlines() if ln.strip()]
    if lines:
        translated = lines[-1]
    # Strip think/thought artifacts (Qwen CoT leakage)
    translated = re.sub(r'</?think>', '', translated, flags=re.IGNORECASE).strip()
    translated = re.sub(r'</?thought>', '', translated, flags=re.IGNORECASE).strip()
    # Strip markdown bold and italic (unwrapped)
    translated = re.sub(r'\*\*(.+?)\*\*', r'\1', translated)
    translated = re.sub(r'\*(.+?)\*', r'\1', translated)
    # Strip smart quotes that wrap the entire term
    translated = translated.strip('\u201c\u201d\u2018\u2019"\'"')
    # Strip parenthetical annotations (definitions, literal translations)
    translated = re.sub(r'\s*\([^)]*\)\s*', ' ', translated).strip()
    # Strip trailing period for multi-word results
    if ' ' in translated:
        translated = translated.rstrip('.。')
    # Handle semicolons: take first segment
    if ';' in translated:
        translated = translated.split(';')[0].strip()
    # Reject if Chinese characters remain
    if re.search(r'[\u4e00-\u9fff]', translated):
        translated = ''
    return translated
