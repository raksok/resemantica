from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from loguru import logger

from resemantica.llm.client import LLMClient


class _FakeCompletions:
    def __init__(self, *, usage: Any | None = None) -> None:
        self.calls: list[dict[str, Any]] = []
        self.usage = usage

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        message = type("Message", (), {"content": "ok"})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice], "usage": self.usage})()


class _FakeChat:
    def __init__(self, completions: _FakeCompletions) -> None:
        self.completions = completions


class _FakeOpenAIClient:
    def __init__(self, *, usage: Any | None = None) -> None:
        self.completions = _FakeCompletions(usage=usage)
        self.chat = _FakeChat(self.completions)


class _FlakyCompletions:
    def __init__(self) -> None:
        self.calls = 0

    def create(self, **kwargs: Any) -> Any:  # noqa: ARG002
        self.calls += 1
        if self.calls == 1:
            raise RuntimeError("temporary outage")
        message = type("Message", (), {"content": "ok"})()
        choice = type("Choice", (), {"message": message})()
        return type("Response", (), {"choices": [choice], "usage": None})()


class _FlakyOpenAIClient:
    def __init__(self) -> None:
        self.completions = _FlakyCompletions()
        self.chat = _FakeChat(self.completions)


class _ConcurrentCompletions:
    def __init__(self, *, fail: bool = False) -> None:
        self.active_by_model: dict[str, int] = {}
        self.max_active_by_model: dict[str, int] = {}
        self.max_active_total = 0
        self._active_total = 0
        self._fail = fail
        self._lock = threading.Lock()

    def create(self, **kwargs: Any) -> Any:
        model = str(kwargs["model"])
        with self._lock:
            self.active_by_model[model] = self.active_by_model.get(model, 0) + 1
            self._active_total += 1
            self.max_active_by_model[model] = max(
                self.max_active_by_model.get(model, 0),
                self.active_by_model[model],
            )
            self.max_active_total = max(self.max_active_total, self._active_total)
        try:
            time.sleep(0.02)
            if self._fail:
                raise RuntimeError("boom")
            message = type("Message", (), {"content": "ok"})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice], "usage": None})()
        finally:
            with self._lock:
                self.active_by_model[model] -= 1
                self._active_total -= 1


class _ConcurrentOpenAIClient:
    def __init__(self, *, fail: bool = False) -> None:
        self.completions = _ConcurrentCompletions(fail=fail)
        self.chat = _FakeChat(self.completions)


def test_generate_text_reuses_openai_client_and_keeps_requests_stateless(monkeypatch) -> None:
    built: list[_FakeOpenAIClient] = []

    def build_client(self: LLMClient) -> _FakeOpenAIClient:  # noqa: ARG001
        client = _FakeOpenAIClient()
        built.append(client)
        return client

    monkeypatch.setattr(LLMClient, "_build_openai_client", build_client)
    client = LLMClient(base_url="http://local", timeout_seconds=30)

    assert client.generate_text(model_name="model-a", prompt="first") == "ok"
    assert client.generate_text(model_name="model-b", prompt="second") == "ok"

    assert len(built) == 1
    calls = built[0].completions.calls
    assert [call["model"] for call in calls] == ["model-a", "model-b"]
    assert calls[0]["messages"] == [{"role": "user", "content": "first"}]
    assert calls[1]["messages"] == [{"role": "user", "content": "second"}]
    assert client.openai_request_count == 2


def test_generate_text_forwards_max_tokens_when_set(monkeypatch) -> None:
    built: list[_FakeOpenAIClient] = []

    def build_client(self: LLMClient) -> _FakeOpenAIClient:  # noqa: ARG001
        client = _FakeOpenAIClient()
        built.append(client)
        return client

    monkeypatch.setattr(LLMClient, "_build_openai_client", build_client)
    client = LLMClient(base_url="http://local", timeout_seconds=30)

    assert client.generate_text(model_name="model-a", prompt="first", max_tokens=64) == "ok"
    assert client.generate_text(model_name="model-a", prompt="second") == "ok"

    calls = built[0].completions.calls
    assert calls[0]["max_tokens"] == 64
    assert "max_tokens" not in calls[1]


def test_generate_text_adds_system_prompt_for_grouped_model(monkeypatch) -> None:
    built: list[_FakeOpenAIClient] = []

    def build_client(self: LLMClient) -> _FakeOpenAIClient:  # noqa: ARG001
        client = _FakeOpenAIClient()
        built.append(client)
        return client

    monkeypatch.setattr(LLMClient, "_build_openai_client", build_client)
    client = LLMClient(
        base_url="http://local",
        timeout_seconds=30,
        throttle_groups={
            "qwen": {
                "model_names": ["qwen-thinking"],
                "max_concurrent_requests": 1,
                "system_prompt": "Qwen system",
            },
        },
    )

    assert client.generate_text(model_name="qwen-thinking", prompt="user prompt") == "ok"

    assert built[0].completions.calls[0]["messages"] == [
        {"role": "system", "content": "Qwen system"},
        {"role": "user", "content": "user prompt"},
    ]


def test_generate_text_ungrouped_model_keeps_user_only_request(monkeypatch) -> None:
    built: list[_FakeOpenAIClient] = []

    def build_client(self: LLMClient) -> _FakeOpenAIClient:  # noqa: ARG001
        client = _FakeOpenAIClient()
        built.append(client)
        return client

    monkeypatch.setattr(LLMClient, "_build_openai_client", build_client)
    client = LLMClient(
        base_url="http://local",
        timeout_seconds=30,
        throttle_groups={
            "qwen": {
                "model_names": ["qwen-thinking"],
                "max_concurrent_requests": 1,
                "system_prompt": "Qwen system",
            },
        },
    )

    assert client.generate_text(model_name="other-model", prompt="user prompt") == "ok"

    assert built[0].completions.calls[0]["messages"] == [
        {"role": "user", "content": "user prompt"},
    ]


def test_generation_hook_bypasses_openai_client(monkeypatch) -> None:
    def fail_build(self: LLMClient) -> None:  # noqa: ARG001
        raise AssertionError("OpenAI client should not be built")

    monkeypatch.setattr(LLMClient, "_build_openai_client", fail_build)
    client = LLMClient(
        base_url="http://local",
        timeout_seconds=30,
        generation_hook=lambda model, prompt: f"{model}:{prompt}",
    )

    assert client.generate_text(model_name="m", prompt="p") == "m:p"
    assert client.openai_request_count == 0


def test_generate_text_tracks_provider_usage(monkeypatch) -> None:
    usage = type(
        "Usage",
        (),
        {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
    )()

    def build_client(self: LLMClient) -> _FakeOpenAIClient:  # noqa: ARG001
        return _FakeOpenAIClient(usage=usage)

    monkeypatch.setattr(LLMClient, "_build_openai_client", build_client)
    client = LLMClient(base_url="http://local", timeout_seconds=30)

    client.generate_text(model_name="model-a", prompt="first")

    snapshot = client.snapshot_usage().to_payload()
    assert snapshot == {
        "llm_request_count": 1,
        "llm_usage_tracked_count": 1,
        "llm_cache_hit_count": 0,
        "llm_prompt_tokens": 11,
        "llm_completion_tokens": 7,
        "llm_total_tokens": 18,
    }


def test_cache_hits_and_missing_usage_are_tracked_without_tokens(monkeypatch) -> None:
    def build_client(self: LLMClient) -> _FakeOpenAIClient:  # noqa: ARG001
        return _FakeOpenAIClient()

    monkeypatch.setattr(LLMClient, "_build_openai_client", build_client)
    client = LLMClient(base_url="http://local", timeout_seconds=30)

    client.record_cache_hit()
    client.generate_text(model_name="model-a", prompt="first")

    snapshot = client.snapshot_usage().to_payload()
    assert snapshot == {
        "llm_request_count": 1,
        "llm_usage_tracked_count": 0,
        "llm_cache_hit_count": 1,
        "llm_prompt_tokens": 0,
        "llm_completion_tokens": 0,
        "llm_total_tokens": 0,
    }


def test_generate_text_logs_retry_warning(monkeypatch) -> None:
    flaky = _FlakyOpenAIClient()

    def build_client(self: LLMClient) -> _FlakyOpenAIClient:  # noqa: ARG001
        return flaky

    messages: list[str] = []
    sink_id = logger.add(lambda message: messages.append(str(message)), level="DEBUG", format="{message}")
    monkeypatch.setattr(LLMClient, "_build_openai_client", build_client)
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    try:
        client = LLMClient(base_url="http://local", timeout_seconds=30, max_retries=2)
        assert client.generate_text(model_name="model-a", prompt="first") == "ok"
    finally:
        logger.remove(sink_id)

    log_output = "\n".join(messages)
    assert "LLM request failed; retrying" in log_output
    assert "model=model-a" in log_output
    assert "attempt=1" in log_output
    assert "max_retries=2" in log_output
    assert "temporary outage" in log_output
    assert flaky.completions.calls == 2


def test_same_model_requests_obey_per_model_concurrency_limit() -> None:
    openai_client = _ConcurrentOpenAIClient()
    client = LLMClient(
        base_url="http://local",
        timeout_seconds=30,
        max_concurrent_requests_per_model=1,
    )
    client._openai_client = openai_client

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(
            executor.map(
                lambda _: client.generate_text(model_name="throttle-same", prompt="p"),
                range(8),
            )
        )

    assert results == ["ok"] * 8
    assert openai_client.completions.max_active_by_model["throttle-same"] == 1


def test_different_models_have_independent_concurrency_keys() -> None:
    openai_client = _ConcurrentOpenAIClient()
    client = LLMClient(
        base_url="http://local",
        timeout_seconds=30,
        max_concurrent_requests_per_model=1,
    )
    client._openai_client = openai_client

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(client.generate_text, model_name="throttle-model-a", prompt="p"),
            executor.submit(client.generate_text, model_name="throttle-model-b", prompt="p"),
        ]
        results = [future.result(timeout=1) for future in futures]

    assert results == ["ok", "ok"]
    assert openai_client.completions.max_active_total == 2


def test_throttle_group_serializes_different_model_names() -> None:
    openai_client = _ConcurrentOpenAIClient()
    client = LLMClient(
        base_url="http://local",
        timeout_seconds=30,
        max_concurrent_requests_per_model=4,
        throttle_groups={
            "qwen": {
                "model_names": ["qwen-thinking", "qwen-nonthinking"],
                "max_concurrent_requests": 1,
            },
        },
    )
    client._openai_client = openai_client

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [
            executor.submit(client.generate_text, model_name="qwen-thinking", prompt="p"),
            executor.submit(client.generate_text, model_name="qwen-nonthinking", prompt="p"),
        ]
        results = [future.result(timeout=1) for future in futures]

    assert results == ["ok", "ok"]
    assert openai_client.completions.max_active_total == 1


def test_concurrency_limit_uses_matching_throttle_group() -> None:
    client = LLMClient(
        base_url="http://local",
        timeout_seconds=30,
        max_concurrent_requests_per_model=1,
        throttle_groups={
            "analysts": {
                "model_names": ["analyst"],
                "max_concurrent_requests": 3,
            }
        },
    )

    assert client.concurrency_limit("analyst") == 3
    assert client.concurrency_limit("translator") == 1


def test_model_semaphore_releases_after_exception() -> None:
    client = LLMClient(
        base_url="http://local",
        timeout_seconds=30,
        max_retries=0,
        max_concurrent_requests_per_model=1,
    )
    client._openai_client = _ConcurrentOpenAIClient(fail=True)

    with pytest.raises(RuntimeError, match="LLM generation failed"):
        client.generate_text(model_name="throttle-exception", prompt="p")

    client._openai_client = _ConcurrentOpenAIClient()
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(
            client.generate_text,
            model_name="throttle-exception",
            prompt="p",
        )
        assert future.result(timeout=1) == "ok"


def test_translate_glossary_candidate_cleans_markdown_bold() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "**Azure Sect**")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="Azure Sect", category="faction", evidence_snippet="ctx",
    )
    assert result == "Azure Sect"


def test_translate_glossary_candidate_cleans_markdown_italic() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "*small town*")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="small town", category="location", evidence_snippet="ctx",
    )
    assert result == "small town"


def test_translate_glossary_candidate_cleans_think_tag() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "</think>\nChen Ping'an")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="Chen Ping'an", category="character", evidence_snippet="ctx",
    )
    assert result == "Chen Ping'an"


def test_translate_glossary_candidate_cleans_parenthetical() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "xianxia (traditional Chinese fantasy)")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="xianxia", category="concept", evidence_snippet="ctx",
    )
    assert result == "xianxia"


def test_translate_glossary_candidate_cleans_semicolons() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "Peaceful; safe; secure.")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="peaceful", category="concept", evidence_snippet="ctx",
    )
    assert result == "Peaceful"


def test_translate_glossary_candidate_rejects_chinese_chars() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "Azure Sect崔东山")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="崔东山", category="character", evidence_snippet="ctx",
    )
    assert result == ""


def test_translate_glossary_candidate_cleans_smart_quotes() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "\u201cAzure Sect\u201d")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="Azure Sect", category="faction", evidence_snippet="ctx",
    )
    assert result == "Azure Sect"


def test_translate_glossary_candidate_cleans_label_prefix() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "Translation: Azure Sect")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="Azure Sect", category="faction", evidence_snippet="ctx",
    )
    assert result == "Azure Sect"


def test_translate_glossary_candidate_cleans_english_prefix() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "English: Azure Sect")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="Azure Sect", category="faction", evidence_snippet="ctx",
    )
    assert result == "Azure Sect"


def test_translate_glossary_candidate_cleans_trailing_period() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "small town.")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="small town", category="location", evidence_snippet="ctx",
    )
    assert result == "small town"


def test_translate_glossary_candidate_cleans_cot_then_answer() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "I think this refers to a sect.\nAzure Sect")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="Azure Sect", category="faction", evidence_snippet="ctx",
    )
    assert result == "Azure Sect"


def test_translate_glossary_candidate_passes_clean_term() -> None:
    client = LLMClient(base_url="http://local", timeout_seconds=30,
                       generation_hook=lambda m, p: "Chen Ping'an")
    result = client.translate_glossary_candidate(
        model_name="test", prompt_template="translate {SOURCE_TERM}",
        source_term="Chen Ping'an", category="character", evidence_snippet="ctx",
    )
    assert result == "Chen Ping'an"
