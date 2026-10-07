import asyncio
import os
import uuid
from collections.abc import Callable

from .cancellation import Cancellation, interruptible
from .errors import safe_failure
from .json_types import Json, Object, dumps, now, utf8


class Output:
    def __init__(self, fd: int = 1) -> None:
        self.fd = fd
        self.abandoned = False
        self.on_error: Callable[[], None] | None = None
        os.set_blocking(fd, False)

    async def write(self, text: str) -> None:
        data = utf8(text)
        view = memoryview(data)
        try:
            while view:
                if self.abandoned:
                    raise BrokenPipeError
                try:
                    written = os.write(self.fd, view)
                    view = view[written:]
                except BlockingIOError:
                    loop = asyncio.get_running_loop()
                    ready: asyncio.Future[None] = loop.create_future()

                    def writable(ready: asyncio.Future[None] = ready) -> None:
                        if not ready.done():
                            ready.set_result(None)

                    loop.add_writer(self.fd, writable)
                    try:
                        await ready
                    finally:
                        loop.remove_writer(self.fd)
        except OSError:
            if self.on_error is not None:
                self.on_error()
            raise

    def abandon(self) -> None:
        self.abandoned = True
        try:
            os.close(self.fd)
        except OSError:
            pass


class EventStream:
    def __init__(self, output: Output) -> None:
        self.output = output
        self.run_id = str(uuid.uuid4())
        self.labels: Object | None = None
        self.text_only = False
        self.sequence = 0
        self.finished = False
        self.last: asyncio.Task[None] | None = None
        self.tasks: set[asyncio.Task[None]] = set()

    def identity(self, run_id: str, labels: Object | None) -> None:
        self.run_id, self.labels = run_id, labels

    def emit(self, type_: str, data: Object | None = None) -> None:
        if self.finished:
            return
        data = data or {}
        self.sequence += 1
        record: Object = {
            "runId": self.run_id,
            "seq": self.sequence,
            "at": now(),
            **({"labels": self.labels} if self.labels is not None else {}),
            "type": type_,
            **data,
        }
        if type_ == "finished":
            self.finished = True
        text = (
            str(data["text"])
            if self.text_only and type_ == "text" and "parentCallId" not in data
            else ""
            if self.text_only
            else dumps(record) + "\n"
        )
        if text:
            previous = self.last

            async def write() -> None:
                if previous is not None:
                    await previous
                await self.output.write(text)

            self.last = asyncio.create_task(write())
            self.tasks.add(self.last)

            def done(task: asyncio.Task[None]) -> None:
                self.tasks.discard(task)
                if not task.cancelled():
                    task.exception()

            self.last.add_done_callback(done)

    async def flush(self, cancellation: Cancellation | None = None) -> None:
        if self.last is not None:
            # A stop interrupts waiting without cancelling queued event writes.
            await interruptible(asyncio.shield(self.last), cancellation)

    async def finish(
        self, error: BaseException | None = None, cancelled: bool = False, data: Object | None = None
    ) -> int:
        self.emit(
            "finished",
            {
                "outcome": "cancelled" if cancelled else "completed" if error is None else "failed",
                **({"error": safe_failure(error)} if error is not None and not cancelled else {}),
                "producedOutput": False,
                "unfinishedCalls": [],
                **(data or {}),
            },
        )
        await self.flush()
        return 2 if cancelled else 0 if error is None else 1

    def abandon(self) -> None:
        self.output.abandon()
        for task in self.tasks:
            task.cancel()


async def write_json(output: Output, value: Json) -> None:
    await output.write(dumps(value) + "\n")
