from __future__ import annotations

from threading import Event, Thread

from resemantica.orchestration.drain import DrainResult, run_interruptible_pool
from resemantica.orchestration.stop import StopToken


def test_interruptible_pool_drains_active_and_never_starts_pending() -> None:
    started = Event()
    release = Event()
    token = StopToken()
    worker_calls: list[int] = []
    consumed: list[int] = []
    outcome: list[DrainResult] = []

    def worker(item: int) -> int:
        worker_calls.append(item)
        started.set()
        assert release.wait(timeout=5)
        return item * 10

    def run() -> None:
        outcome.append(
            run_interruptible_pool(
                [1, 2, 3],
                max_workers=1,
                stop_token=token,
                worker=worker,
                consume=lambda _item, result: consumed.append(result),
            )
        )

    thread = Thread(target=run)
    thread.start()
    assert started.wait(timeout=5)
    token.request_stop()
    release.set()
    thread.join(timeout=5)

    assert not thread.is_alive()
    assert worker_calls == [1]
    assert consumed == [10]
    assert outcome == [
        DrainResult(
            stopped=True,
            completed_unit_ids=("1",),
            drained_unit_ids=("1",),
            canceled_count=2,
        )
    ]


def test_interruptible_pool_returns_without_starting_when_already_stopped() -> None:
    token = StopToken()
    token.request_stop()
    calls: list[int] = []

    result = run_interruptible_pool(
        [1, 2],
        max_workers=2,
        stop_token=token,
        worker=lambda item: calls.append(item),
        consume=lambda _item, _result: None,
    )

    assert calls == []
    assert result.stopped is True
    assert result.completed_unit_ids == ()
    assert result.drained_unit_ids == ()
    assert result.canceled_count == 2
