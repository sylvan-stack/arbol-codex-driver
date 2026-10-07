import asyncio
import time
from collections.abc import Awaitable
from typing import cast

from .errors import Failure


class Cancellation:
    def __init__(self) -> None:
        self.event = asyncio.Event()
        self.stopped_at: float | None = None

    @property
    def aborted(self) -> bool:
        return self.event.is_set()

    def abort(self) -> None:
        if not self.aborted:
            self.stopped_at = time.monotonic()
            self.event.set()

    def check(self) -> None:
        if self.aborted:
            raise Failure("tool_failed", "The codex operation was cancelled.")


async def interruptible[T](
    work: Awaitable[T], cancellation: Cancellation | None = None, timeout: float | None = None
) -> T:
    task = asyncio.ensure_future(work)
    stop = asyncio.create_task(cancellation.event.wait()) if cancellation is not None else None
    try:
        if cancellation is not None:
            cancellation.check()
        pending: set[asyncio.Future[object]] = {cast(asyncio.Future[object], task)}
        if stop is not None:
            pending.add(cast(asyncio.Future[object], stop))
        done, _ = await asyncio.wait(pending, timeout=timeout, return_when=asyncio.FIRST_COMPLETED)
        if cancellation is not None:
            cancellation.check()
        if task not in done:
            raise TimeoutError
        return task.result()
    finally:
        if stop is not None:
            stop.cancel()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, *([] if stop is None else [stop]), return_exceptions=True)
