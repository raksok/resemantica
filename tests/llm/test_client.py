from __future__ import annotations

from typing import Any

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
