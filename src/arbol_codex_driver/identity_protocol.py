"""Bounded identity wire values and private, durable protocol files.

These helpers do not admit a caller or repair state. Callers must hold the
specified component/state/Subscription authority before using a file helper.
Legacy record serialization deliberately stays in json_types.
"""

import base64
import hashlib
import json
import os
import re
import secrets
import stat
import uuid
from pathlib import Path
from types import TracebackType
from typing import cast

from .errors import Failure
from .json_types import Json, Object

DOCUMENT_LIMIT = 4096
MANIFEST_LIMIT = 32 * 1024 * 1024
MANIFEST_ENTRIES = 100000


def invalid() -> Failure:
    return Failure("internal", "Identity protocol state is invalid.")


def object_fields(value: Json, fields: set[str]) -> Object:
    if not isinstance(value, dict) or set(value) != fields:
        raise invalid()
    return value


def integer(value: Json, minimum: int = 0, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or maximum is not None and value > maximum:
        raise invalid()
    return value


def token(value: Json) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[A-Za-z0-9_-]{43}", value) is None:
        raise invalid()
    decoded = base64.urlsafe_b64decode(value + "=")
    if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode("ascii").rstrip("=") != value:
        raise invalid()
    return value


def fresh_token() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii").rstrip("=")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def digest(value: Json) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[0-9a-f]{64}", value) is None:
        raise invalid()
    return value


def canonical_uuid(value: Json) -> str:
    if not isinstance(value, str):
        raise invalid()
    try:
        parsed = uuid.UUID(value)
    except ValueError:
        raise invalid() from None
    if str(parsed) != value:
        raise invalid()
    return value


def relative_path(value: Json) -> str:
    if not isinstance(value, str) or not value or "\\" in value or "\x00" in value:
        raise invalid()
    try:
        value.encode("utf-8", "strict")
    except UnicodeError:
        raise invalid() from None
    if any(part in ("", ".", "..") for part in value.split("/")):
        raise invalid()
    return value


def physical_path(value: Json) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise invalid()
    path = Path(value)
    try:
        if not path.is_absolute() or str(path) != value or str(path.resolve(strict=True)) != value:
            raise invalid()
    except (OSError, RuntimeError, ValueError):
        raise invalid() from None
    return path


def canonical_bytes(value: Json, limit: int = DOCUMENT_LIMIT) -> bytes:
    try:
        data = (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
            "utf-8", "strict"
        )
    except (ValueError, UnicodeError, TypeError, RecursionError):
        raise invalid() from None
    if len(data) > limit:
        raise invalid()
    return data


def parse_bytes(data: bytes, limit: int = DOCUMENT_LIMIT, *, canonical: bool = True) -> Json:
    if len(data) > limit:
        raise invalid()

    def pairs(items: list[tuple[str, Json]]) -> Object:
        result: Object = {}
        for key, value in items:
            if key in result:
                raise invalid()
            result[key] = value
        return result

    def constant(_: str) -> None:
        raise invalid()

    try:
        value = cast(Json, json.loads(data.decode("utf-8", "strict"), object_pairs_hook=pairs, parse_constant=constant))
        if not isinstance(value, dict) or canonical and canonical_bytes(value, limit) != data:
            raise invalid()
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise invalid() from None


def _safe_name(name: str) -> str:
    if "/" in relative_path(name):
        raise invalid()
    return name


def same_inode(a: os.stat_result, b: os.stat_result) -> bool:
    return (a.st_dev, a.st_ino) == (b.st_dev, b.st_ino)


def private_stat(info: os.stat_result, *, directory: bool = False) -> None:
    expected = 0o700 if directory else 0o600
    if (
        info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != expected
        or not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
    ):
        raise invalid()


class PrivateDirectory:
    """An owned directory reached without following any path-component link."""

    def __init__(self, path: Path) -> None:
        self.path = physical_path(str(path))
        descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            for part in self.path.parts[1:]:
                next_descriptor = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=descriptor
                )
                os.close(descriptor)
                descriptor = next_descriptor
            self.info = os.fstat(descriptor)
            private_stat(self.info, directory=True)
        except BaseException:
            os.close(descriptor)
            raise
        self.fd = descriptor

    def __enter__(self) -> PrivateDirectory:
        return self

    def __exit__(self, kind: type[BaseException] | None, error: BaseException | None, tb: TracebackType | None) -> None:
        os.close(self.fd)

    def check(self) -> None:
        current = os.stat(self.path, follow_symlinks=False)
        private_stat(current, directory=True)
        if not same_inode(current, self.info) or str(self.path.resolve(strict=True)) != str(self.path):
            raise invalid()

    def _existing(self, name: str) -> os.stat_result | None:
        try:
            info = os.stat(_safe_name(name), dir_fd=self.fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        private_stat(info)
        return info

    def read(self, name: str, limit: int = DOCUMENT_LIMIT) -> bytes | None:
        self.check()
        name = _safe_name(name)
        try:
            descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=self.fd)
        except FileNotFoundError:
            return None
        try:
            before = os.fstat(descriptor)
            private_stat(before)
            if before.st_size > limit:
                raise invalid()
            chunks = bytearray()
            while len(chunks) <= limit:
                part = os.read(descriptor, min(65536, limit + 1 - len(chunks)))
                if not part:
                    break
                chunks.extend(part)
            after = os.fstat(descriptor)
            current = self._existing(name)
            if (
                len(chunks) > limit
                or current is None
                or not same_inode(before, current)
                or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
                != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            ):
                raise invalid()
            self.check()
            return bytes(chunks)
        finally:
            os.close(descriptor)

    def publish(self, name: str, data: bytes, limit: int = DOCUMENT_LIMIT) -> None:
        self.check()
        name = _safe_name(name)
        if len(data) > limit:
            raise invalid()
        self._existing(name)
        temporary = ".write-identity-" + fresh_token()
        descriptor = os.open(
            temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600, dir_fd=self.fd
        )
        published = False
        try:
            view = memoryview(data)
            while view:
                count = os.write(descriptor, view)
                if count <= 0:
                    raise invalid()
                view = view[count:]
            os.fsync(descriptor)
            self.check()
            self._existing(name)
            os.replace(temporary, name, src_dir_fd=self.fd, dst_dir_fd=self.fd)
            published = True
            os.fsync(self.fd)
        finally:
            os.close(descriptor)
            if not published:
                os.unlink(temporary, dir_fd=self.fd)
                os.fsync(self.fd)

    def delete(self, name: str) -> None:
        self.check()
        name = _safe_name(name)
        if self._existing(name) is not None:
            os.unlink(name, dir_fd=self.fd)
            os.fsync(self.fd)
        self.check()
