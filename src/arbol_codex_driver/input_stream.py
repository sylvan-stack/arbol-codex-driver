import asyncio
import sys


class Input:
    def __init__(self) -> None:
        self.reader = asyncio.StreamReader()
        self.transport: asyncio.ReadTransport | None = None
        self.buffer = b""
        self.eof = False

    async def open(self) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(self.reader), sys.stdin.buffer)
        self.transport = transport

    async def line(self) -> str | None:
        while b"\n" not in self.buffer and not self.eof:
            chunk = await self.reader.read(65536)
            if not chunk:
                self.eof = True
            self.buffer += chunk
        if b"\n" in self.buffer:
            line, self.buffer = self.buffer.split(b"\n", 1)
        elif self.buffer:
            line, self.buffer = self.buffer, b""
        else:
            return None
        return line.removesuffix(b"\r").decode("utf-8", "replace")

    def close(self) -> None:
        if self.transport is not None:
            self.transport.close()
        self.eof = True
        self.reader.feed_eof()
