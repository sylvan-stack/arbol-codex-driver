"""Exact Darwin admission identities, separate from historical Driver owners.

The public proc_bsdinfo ABI supplies integer kernel start microseconds. This
adapter is not a custody oracle and has no ps/wall-clock/tolerant fallback.
"""

import ctypes
import errno
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import TypedDict, cast

from .identity_protocol import canonical_uuid, integer, invalid, object_fields
from .json_types import Json

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MAX_SECONDS = 253402300799


class Identity(TypedDict):
    pid: int
    startedAt: str


class BsdInfo(ctypes.Structure):
    """sys/proc_info.h proc_bsdinfo, qualified 64-bit Darwin layout."""

    _fields_ = [
        ("flags", ctypes.c_uint32), ("status", ctypes.c_uint32), ("xstatus", ctypes.c_uint32),
        ("pid", ctypes.c_uint32), ("ppid", ctypes.c_uint32), ("uid", ctypes.c_uint32),
        ("gid", ctypes.c_uint32), ("ruid", ctypes.c_uint32), ("rgid", ctypes.c_uint32),
        ("svuid", ctypes.c_uint32), ("svgid", ctypes.c_uint32), ("reserved", ctypes.c_uint32),
        ("comm", ctypes.c_char * 16), ("name", ctypes.c_char * 32),
        ("nfiles", ctypes.c_uint32), ("pgid", ctypes.c_uint32), ("jobc", ctypes.c_uint32),
        ("tdev", ctypes.c_uint32), ("tpgid", ctypes.c_uint32), ("nice", ctypes.c_int32),
        ("start_sec", ctypes.c_uint64), ("start_usec", ctypes.c_uint64),
    ]


@lru_cache(maxsize=1)
def library() -> ctypes.CDLL:
    if (
        sys.platform != "darwin" or ctypes.sizeof(ctypes.c_void_p) != 8
        or ctypes.sizeof(BsdInfo) != 136 or ctypes.alignment(BsdInfo) != 8
        or BsdInfo.pid.offset != 12 or BsdInfo.status.offset != 4
        or BsdInfo.start_sec.offset != 120 or BsdInfo.start_usec.offset != 128
    ):
        raise invalid()
    try:
        result = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True)
        result.proc_pidinfo.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_uint64, ctypes.c_void_p, ctypes.c_int]
        result.proc_pidinfo.restype = ctypes.c_int
        return result
    except (OSError, AttributeError):
        raise invalid() from None


def start_string(seconds: int, microseconds: int) -> str:
    integer(seconds, 1, _MAX_SECONDS)
    integer(microseconds, 0, 999999)
    try:
        value = _EPOCH + timedelta(seconds=seconds, microseconds=microseconds)
        return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
    except (OverflowError, ValueError):
        raise invalid() from None


def canonical_start(value: Json) -> str:
    if not isinstance(value, str) or re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z", value) is None:
        raise invalid()
    try:
        parsed = datetime.fromisoformat(value)
        elapsed = parsed - _EPOCH
        seconds = elapsed.days * 86400 + elapsed.seconds
        if start_string(seconds, elapsed.microseconds) != value:
            raise invalid()
    except (ValueError, OverflowError):
        raise invalid() from None
    return value


def identity_record(value: Json) -> Identity:
    row = object_fields(value, {"pid", "startedAt"})
    return {"pid": integer(row["pid"], 1, (1 << 31) - 1), "startedAt": canonical_start(row["startedAt"])}


@dataclass(frozen=True)
class Process:
    identity: Identity
    parent: int
    group: int


def inspect(pid: int) -> Process | None:
    integer(pid, 1, (1 << 31) - 1)
    value = BsdInfo()
    ctypes.set_errno(0)
    count = library().proc_pidinfo(pid, 3, 0, ctypes.byref(value), ctypes.sizeof(value))
    error = ctypes.get_errno()
    if count == 0 and error == errno.ESRCH:
        return None
    if count != 136 or error or value.pid != pid:
        raise invalid()
    if value.status == 5:  # Public sys/proc.h SZOMB is not a live identity.
        return None
    if value.status not in (2, 3, 4) or value.uid != os.getuid() or not value.ppid or not value.pgid:
        raise invalid()
    identity: Identity = {"pid": pid, "startedAt": start_string(value.start_sec, value.start_usec)}
    return Process(identity, int(value.ppid), int(value.pgid))


def process_identity(pid: int) -> Identity:
    value = inspect(pid)
    if value is None:
        raise invalid()
    return value.identity


def matches(identity: Identity, *, parent: int | None = None) -> bool:
    expected = identity_record(cast(Json, identity))
    observed = inspect(expected["pid"])
    return observed is not None and observed.identity == expected and (parent is None or observed.parent == parent)


def boot_uuid() -> str:
    try:
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"],
            env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
            capture_output=True, timeout=5, check=False,
        )
        if result.returncode or len(result.stdout) > 128:
            raise invalid()
        text = result.stdout.decode("ascii", "strict")
        if re.fullmatch(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}\n?", text) is None:
            raise invalid()
        return canonical_uuid(text.rstrip("\n").lower())
    except (OSError, UnicodeError, subprocess.TimeoutExpired):
        raise invalid() from None
