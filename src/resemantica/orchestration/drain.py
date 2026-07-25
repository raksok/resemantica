from __future__ import annotations

from collections.abc import Callable, Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from typing import TypeVar

from .stop import StopToken

T = TypeVar("T")
R = TypeVar("R")


@dataclass(frozen=True, slots=True)
class DrainResult:
    stopped: bool
    completed_unit_ids: tuple[str, ...]
    drained_unit_ids: tuple[str, ...]
    canceled_count: int


def run_interruptible_pool(
    items: Sequence[T],
    *,
    max_workers: int,
    stop_token: StopToken | None,
    worker: Callable[[T], R],
    consume: Callable[[T, R], None],
    unit_id: Callable[[T], str] = str,
) -> DrainResult:
    """Run a bounded rolling window and drain only work active at stop time."""
    if max_workers < 1:
        raise ValueError("max_workers must be >= 1")

    completed_ids: list[str] = []
    drained_ids: list[str] = []
    next_index = 0
    stopping = bool(stop_token and stop_token.requested)
    futures: dict[Future[R], T] = {}
    executor = ThreadPoolExecutor(max_workers=max_workers)

    def submit_available() -> None:
        nonlocal next_index
        while not stopping and len(futures) < max_workers and next_index < len(items):
            item = items[next_index]
            next_index += 1
            futures[executor.submit(worker, item)] = item

    try:
        submit_available()
        while futures:
            if not stopping and stop_token is not None and stop_token.requested:
                stopping = True
                for future in tuple(futures):
                    future.cancel()

            done, _ = wait(tuple(futures), timeout=0.1, return_when=FIRST_COMPLETED)
            if not done:
                continue
            if not stopping and stop_token is not None and stop_token.requested:
                stopping = True
                for future in tuple(futures):
                    if future not in done:
                        future.cancel()

            for future in done:
                item = futures.pop(future)
                if future.cancelled():
                    continue
                result = future.result()
                consume(item, result)
                identifier = unit_id(item)
                completed_ids.append(identifier)
                if stopping:
                    drained_ids.append(identifier)

            if not stopping:
                submit_available()
    finally:
        executor.shutdown(wait=True, cancel_futures=True)

    return DrainResult(
        stopped=stopping,
        completed_unit_ids=tuple(completed_ids),
        drained_unit_ids=tuple(drained_ids),
        canceled_count=max(0, len(items) - len(completed_ids)),
    )
