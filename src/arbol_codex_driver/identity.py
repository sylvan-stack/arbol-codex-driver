"""Local format admission, independent of Subscription records and credentials.

The independently opened guard survives until explicit settled close or process
exit. There is no destructor which could release admission before final output.
"""

import fcntl
import os
import re
import stat
import time
from dataclasses import dataclass
from pathlib import Path

from .errors import Failure
from .identity_protocol import (
    PrivateDirectory,
    canonical_bytes,
    fresh_token,
    invalid,
    object_fields,
    parse_bytes,
    private_stat,
    same_inode,
    token,
)

DATA_FORMAT = 2


def state_format(root: Path) -> int | None:
    """Read-only unsupported-format preflight; never an admission grant."""
    if root.resolve(strict=False) != root:
        raise invalid()
    path = root / "format"
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    except FileNotFoundError:
        return None
    try:
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode) or before.st_uid != os.getuid() or before.st_size > 4096:
            raise invalid()
        raw = os.read(descriptor, 4097)
        after, named = os.fstat(descriptor), path.lstat()
        if (
            not same_inode(before, named)
            or (before.st_size, before.st_mtime_ns, before.st_ctime_ns)
            != (after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            or len(raw) != before.st_size
        ):
            raise invalid()
    finally:
        os.close(descriptor)
    try:
        text = raw.decode("ascii").strip()
    except UnicodeError:
        raise invalid() from None
    if re.fullmatch(r"[1-9][0-9]*", text, re.ASCII) is None:
        raise invalid()
    number = int(text)
    if number > DATA_FORMAT:
        raise Failure(
            "state_newer",
            f"State format {number} is newer than supported format {DATA_FORMAT}.",
            {"remedy": "Run the Build that wrote this state, or a newer one."},
        )
    if number == 2 and (raw != b"2\n" or stat.S_IMODE(before.st_mode) != 0o600):
        raise invalid()
    return number


def _sync(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prepare_directory(root: Path, *, harden: bool = True) -> None:
    if root.resolve(strict=False) != root:
        raise invalid()
    if not root.exists():
        if not root.parent.exists():
            _prepare_directory(root.parent)
        try:
            root.mkdir(mode=0o700)
            _sync(root.parent)
        except FileExistsError:
            pass
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        current = os.fstat(descriptor)
        if current.st_uid != os.getuid() or not same_inode(current, root.lstat()):
            raise invalid()
        # Preserve legacy initialization's permission hardening, only after
        # the unsupported-format preflight above has refused newer state.
        if stat.S_IMODE(current.st_mode) != 0o700:
            if not harden:
                raise invalid()
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
            _sync(root.parent)
        private_stat(os.fstat(descriptor), directory=True)
    finally:
        os.close(descriptor)


def root_generation(root: Path) -> str:
    with PrivateDirectory(root) as directory:
        raw = directory.read("identity.json")
        if raw is None:
            raise invalid()
        value = object_fields(parse_bytes(raw), {"version", "generation"})
        if type(value["version"]) is not int or value["version"] != 1:
            raise invalid()
        return token(value["generation"])


def _qualified() -> bool:
    from .admission import current_session

    try:
        current_session()
    except Failure:
        return False
    return True


@dataclass
class IdentityState:
    directory: Path
    descriptor: int
    format: int
    generation: str | None
    closed: bool = False

    @classmethod
    def open(cls, root: Path) -> IdentityState:
        preflight = state_format(root)
        qualified = _qualified()
        if preflight != 1 and not qualified:
            raise invalid()
        _prepare_directory(root, harden=preflight != 2)
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        if preflight != 2:
            flags |= os.O_CREAT
        # Existing format2 must retain its original inode. Never recreate a
        # missing guard while another invocation may still hold its old one.
        descriptor = os.open(root / "identity.guard", flags, 0o600)
        try:
            result = cls(root, descriptor, 1, None)
            result.check_guard()
            os.fsync(descriptor)
            _sync(root)
            result.lock(exclusive=False)
            number = state_format(root)
            if number is None:
                result.lock(exclusive=True)
                number = state_format(root)
                if number is None:
                    if not qualified or set(root.iterdir()) != {root / "identity.guard"}:
                        raise invalid()
                    generation = fresh_token()
                    with PrivateDirectory(root) as directory:
                        # Fence old writers first; a crash thereafter leaves
                        # incomplete format2 refused, never silently repaired.
                        directory.publish("format", b"2\n")
                        directory.publish("identity.json", canonical_bytes({"version": 1, "generation": generation}))
                    number = 2
                result.lock(exclusive=False)
            if number == 2 and not qualified:
                raise invalid()
            result.format = number
            if number == 1:
                with PrivateDirectory(root) as directory:
                    marker = os.open("format", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory.fd)
                    try:
                        if not same_inode(os.fstat(marker), (root / "format").lstat()):
                            raise invalid()
                        os.fchmod(marker, 0o600)
                        os.fsync(marker)
                        os.fsync(directory.fd)
                    finally:
                        os.close(marker)
            else:
                result.generation = root_generation(root)
            result.check()
            return result
        except BaseException:
            os.close(descriptor)
            raise

    def check_guard(self) -> None:
        if self.closed:
            raise invalid()
        with PrivateDirectory(self.directory) as directory:
            current = os.fstat(self.descriptor)
            private_stat(current)
            named = os.stat("identity.guard", dir_fd=directory.fd, follow_symlinks=False)
            if not same_inode(current, named) or current.st_nlink != 1:
                raise invalid()

    def lock(self, *, exclusive: bool) -> None:
        deadline = time.monotonic() + 20
        while True:
            try:
                fcntl.flock(self.descriptor, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
                self.check_guard()
                return
            except BlockingIOError:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise Failure("in_use", "Driver state is held for identity maintenance.") from None
                time.sleep(min(0.01, remaining))

    def check(self) -> None:
        self.check_guard()
        if state_format(self.directory) != self.format:
            raise invalid()
        with PrivateDirectory(self.directory) as directory:
            for name in ("identity-upgrade.json", "identity-maintenance.json"):
                try:
                    os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
                except FileNotFoundError:
                    continue
                raise invalid()
        if self.format == 2 and root_generation(self.directory) != self.generation:
            raise invalid()

    def close(self) -> None:
        if not self.closed:
            self.check()
            self.closed = True
            os.close(self.descriptor)  # Never LOCK_UN a shared description.
