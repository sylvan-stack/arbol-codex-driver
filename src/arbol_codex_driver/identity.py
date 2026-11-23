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
from .json_types import Json, Object

DATA_FORMAT = 2


def canonical_id(value: str) -> str:
    if not isinstance(value, str) or re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}", value, re.ASCII) is None:
        raise Failure("invalid_input", "The Subscription identifier is not a safe file name.")
    return value


def expected_proof(value: str | None) -> tuple[str, str] | None:
    if value is None:
        return None
    if isinstance(value, str) and len(value) == 87:
        parts = value.split(".")
        if len(parts) == 2:
            try:
                return token(parts[0]), token(parts[1])
            except Failure:
                pass
    raise Failure("invalid_input", "Give --expect exactly one canonical generation.witness pair.")


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
        if preflight == 1:
            raise Failure(
                "invalid_input",
                "This Build requires Driver state layout 2. Migrate the directory under exclusive maintenance.",
            )
        if not _qualified():
            raise invalid()
        _prepare_directory(root, harden=preflight != 2)
        flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
        if preflight != 2:
            flags |= os.O_CREAT
        # Existing format2 must retain its original inode. Never recreate a
        # missing guard while another invocation may still hold its old one.
        descriptor = os.open(root / "identity.guard", flags, 0o600)
        try:
            result = cls(root, descriptor, DATA_FORMAT, None)
            result.check_guard()
            os.fsync(descriptor)
            _sync(root)
            result.lock(exclusive=False)
            number = state_format(root)
            if number is None:
                result.lock(exclusive=True)
                number = state_format(root)
                if number is None:
                    if set(root.iterdir()) != {root / "identity.guard"}:
                        raise invalid()
                    generation = fresh_token()
                    with PrivateDirectory(root) as directory:
                        # Fence old writers first; a crash thereafter leaves
                        # incomplete format2 refused, never silently repaired.
                        directory.publish("format", b"2\n")
                        directory.publish("identity.json", canonical_bytes({"version": 1, "generation": generation}))
                    number = 2
                result.lock(exclusive=False)
            if number != DATA_FORMAT:
                raise invalid()
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

    def require_proof(self) -> str:
        self.check()
        if self.format != 2:
            raise Failure(
                "invalid_input",
                "Subscription identity requires upgraded Driver state.",
                {"remedy": "Upgrade Driver state under exclusive maintenance before using Subscription identity."},
            )
        if self.generation is None:
            raise invalid()
        return self.generation

    def capture_proof(self, identifier: str, expected: tuple[str, str] | None) -> Object:
        """Caller holds the short lock and has validated the current record.

        A record's timestamp/auth state never supplies this witness. Pending
        local settlement is unavailable; this operation cannot repair it.
        """
        identifier = canonical_id(identifier)
        generation = self.require_proof()
        with PrivateDirectory(self.directory / "subscriptions" / identifier) as directory:
            try:
                os.stat("identity-pending.json", dir_fd=directory.fd, follow_symlinks=False)
            except FileNotFoundError:
                pass
            else:
                raise invalid()
            raw = directory.read("identity.json")
            sidecar: Object | None = None
            if raw is not None:
                sidecar = object_fields(parse_bytes(raw), {"version", "witness", "state"})
                if (
                    type(sidecar["version"]) is not int
                    or sidecar["version"] != 1
                    or sidecar["state"] not in ("active", "retired")
                ):
                    raise invalid()
                token(sidecar["witness"])
            materialized = sidecar is None or sidecar["state"] == "retired"
            if materialized:
                sidecar = {"version": 1, "witness": fresh_token(), "state": "active"}
                directory.publish("identity.json", canonical_bytes(sidecar))
            assert sidecar is not None
            witness = token(sidecar["witness"])
            self.check()
            if expected is not None and (materialized or expected != (generation, witness)):
                raise Failure(
                    "in_use",
                    "Subscription lifetime changed; select it again and explicitly rebind.",
                    {"remedy": "Select the Subscription again and explicitly replace its browser binding."},
                )
            proof: Object = {
                "version": 1,
                "driver": "codex",
                "subscription": identifier,
                "generation": generation,
                "witness": witness,
            }
            canonical_bytes(proof)  # Keep the successful wire document bounded.
            return proof

    def close(self) -> None:
        if not self.closed:
            self.check()
            self.closed = True
            os.close(self.descriptor)  # Never LOCK_UN a shared description.


@dataclass(frozen=True)
class PendingIdentity:
    """Exact local settlement journal, never an auth or process receipt."""

    operation: str
    witness: str
    phase: str

    @classmethod
    def parse(cls, value: Object) -> PendingIdentity:
        row = object_fields(value, {"version", "operation", "witness", "phase"})
        if (
            type(row["version"]) is not int or row["version"] != 1
            or row["operation"] not in ("create", "remove") or row["phase"] not in ("prepared", "committed")
        ):
            raise invalid()
        return cls(str(row["operation"]), token(row["witness"]), str(row["phase"]))

    def document(self) -> Object:
        value: Object = {"version": 1, "operation": self.operation, "witness": self.witness, "phase": self.phase}
        self.parse(value)
        return value


def subscription_sidecar(directory: PrivateDirectory) -> Object | None:
    raw = directory.read("identity.json")
    if raw is None:
        return None
    value = object_fields(parse_bytes(raw), {"version", "witness", "state"})
    if type(value["version"]) is not int or value["version"] != 1 or value["state"] not in ("active", "retired"):
        raise invalid()
    token(value["witness"])
    return value


@dataclass(frozen=True)
class LifetimeSnapshot:
    """Private captured lifetime, never part of a public Subscription record."""

    subscription: str
    generation: str
    witness: str

    @classmethod
    def parse(cls, value: Json) -> LifetimeSnapshot:
        row = object_fields(value, {"subscription", "generation", "witness"})
        if not isinstance(row["subscription"], str):
            raise invalid()
        return cls(canonical_id(row["subscription"]), token(row["generation"]), token(row["witness"]))

    def document(self) -> Object:
        value: Object = {"subscription": self.subscription, "generation": self.generation, "witness": self.witness}
        self.parse(value)
        return value

    @classmethod
    def capture(cls, state: IdentityState, identifier: str) -> LifetimeSnapshot | None:
        # Caller validates the local record and holds its short lock.
        state.check()
        if state.format == 1:
            return None
        proof = state.capture_proof(identifier, None)
        return cls(canonical_id(identifier), token(proof["generation"]), token(proof["witness"]))


def lifetime_matches(state: IdentityState, identifier: str, snapshot: LifetimeSnapshot | None) -> bool:
    """Compare under the short lock without materializing or repairing identity.

    Legacy callers have no proof. Format2 callers must carry the independently
    captured tokens; a late completion cannot derive them from current state.
    """
    state.check()
    identifier = canonical_id(identifier)
    if state.format == 1:
        return snapshot is None
    if snapshot is None or snapshot.subscription != identifier or snapshot.generation != state.generation:
        return False
    token(snapshot.generation)
    token(snapshot.witness)
    try:
        with PrivateDirectory(state.directory / "subscriptions" / identifier) as directory:
            if IdentityJournal._pending(directory) is not None:
                return False
            sidecar = subscription_sidecar(directory)
            if identifier != "chatgpt" and not IdentityJournal._record_present(directory):
                return False
            return sidecar is not None and sidecar["state"] == "active" and sidecar["witness"] == snapshot.witness
    except FileNotFoundError:
        return False


@dataclass(frozen=True)
class RecoveryObservation:
    """Fresh local state observation, never authority for an old auth result."""

    generation: str
    sidecar: bytes | None

    @classmethod
    def capture(cls, state: IdentityState, identifier: str) -> RecoveryObservation:
        # Caller validates the record under the same short lock. Explicit
        # absent/retired sidecars are observations, never materialized proof.
        generation = state.require_proof()
        with PrivateDirectory(state.directory / "subscriptions" / canonical_id(identifier)) as directory:
            if IdentityJournal._pending(directory) is not None:
                raise invalid()
            sidecar = subscription_sidecar(directory)
            return cls(generation, canonical_bytes(sidecar) if sidecar is not None else None)


@dataclass(frozen=True)
class IdentityJournal:
    """Caller holds the canonical short Subscription lock throughout a method.

    Record validation and original owner/attempt cleanup evidence belong to the
    caller. A journal alone never proves prepared remove cleanup succeeded.
    """

    state: IdentityState
    identifier: str

    def _directory(self) -> PrivateDirectory:
        self.state.require_proof()
        return PrivateDirectory(self.state.directory / "subscriptions" / canonical_id(self.identifier))

    @staticmethod
    def _pending(directory: PrivateDirectory) -> PendingIdentity | None:
        raw = directory.read("identity-pending.json")
        if raw is None:
            return None
        value = parse_bytes(raw)
        assert isinstance(value, dict)
        return PendingIdentity.parse(value)

    def pending(self) -> PendingIdentity | None:
        with self._directory() as directory:
            return self._pending(directory)

    @staticmethod
    def _same(directory: PrivateDirectory, pending: PendingIdentity) -> None:
        pending.document()
        if IdentityJournal._pending(directory) != pending:
            raise invalid()

    @staticmethod
    def _matching_sidecar(directory: PrivateDirectory, witness: str) -> Object | None:
        value = subscription_sidecar(directory)
        if value is not None and value["witness"] != token(witness):
            raise invalid()
        return value

    @staticmethod
    def _record_present(directory: PrivateDirectory) -> bool:
        try:
            info = os.stat("record.json", dir_fd=directory.fd, follow_symlinks=False)
        except FileNotFoundError:
            return False
        private_stat(info)
        return True

    def begin_remove(self, witness: str) -> PendingIdentity:
        if self.identifier == "chatgpt":
            raise Failure("invalid_input", "The native chatgpt Subscription cannot be removed.")
        pending = PendingIdentity("remove", token(witness), "prepared")
        with self._directory() as directory:
            if self._pending(directory) is not None:
                raise invalid()
            sidecar = self._matching_sidecar(directory, pending.witness)
            if sidecar is None or sidecar["state"] != "active" or not self._record_present(directory):
                raise invalid()
            directory.publish("identity-pending.json", canonical_bytes(pending.document()))
            self.state.check()
        return pending

    def cancel_remove(self, pending: PendingIdentity) -> None:
        """Only the original live operation, before any cleanup effect, calls this."""
        if pending.operation != "remove" or pending.phase != "prepared" or self.identifier == "chatgpt":
            raise invalid()
        with self._directory() as directory:
            self._same(directory, pending)
            sidecar = self._matching_sidecar(directory, pending.witness)
            if sidecar is None or sidecar["state"] != "active" or not self._record_present(directory):
                raise invalid()
            directory.delete("identity-pending.json")
            self.state.check()

    def complete_remove(self, pending: PendingIdentity) -> None:
        """Caller proves original cleanup/receipt success, or a committed journal.

        Any current record must have been validated by the caller. Retirement,
        deletion and the committed phase are durable before pending is cleared.
        """
        if pending.operation != "remove" or self.identifier == "chatgpt":
            raise invalid()
        with self._directory() as directory:
            self._same(directory, pending)
            self._matching_sidecar(directory, pending.witness)
            directory.publish("identity.json", canonical_bytes({
                "version": 1, "witness": pending.witness, "state": "retired",
            }))
            directory.delete("record.json")
            committed = PendingIdentity("remove", pending.witness, "committed")
            directory.publish("identity-pending.json", canonical_bytes(committed.document()))
            directory.delete("identity-pending.json")
            self.state.check()

    def settle(self, *, record_present: bool) -> str | None:
        """Caller has validated a present real record; malformed input refuses.

        A dead process, missing progress or an absent record cannot turn a
        prepared remove into success. Explicit conservative maintenance owns it.
        """
        if type(record_present) is not bool:
            raise invalid()
        with self._directory() as directory:
            pending = self._pending(directory)
            if pending is None:
                return None
            if self._record_present(directory) != record_present:
                raise invalid()
            sidecar = self._matching_sidecar(directory, pending.witness)
            if pending.operation == "remove":
                if pending.phase != "committed" or self.identifier == "chatgpt":
                    raise invalid()
            else:
                active = record_present and (sidecar is None or sidecar["state"] == "active")
                state = "active" if active else "retired"
                directory.publish("identity.json", canonical_bytes({
                    "version": 1, "witness": pending.witness, "state": state,
                }))
                committed = PendingIdentity("create", pending.witness, "committed")
                directory.publish("identity-pending.json", canonical_bytes(committed.document()))
                directory.delete("identity-pending.json")
                self.state.check()
                return state
        self.complete_remove(pending)
        return "retired"


def retire_pending(directory: PrivateDirectory, original: PendingIdentity) -> None:
    """Exclusive maintenance + canonical short lock, not original cleanup success.

    The caller binds original to its immutable before-entry and validates any
    current record. No record/credential/progress or root bytes are changed.
    """
    original.document()
    current = IdentityJournal._pending(directory)
    sidecar = subscription_sidecar(directory)
    retired: Object = {"version": 1, "witness": original.witness, "state": "retired"}
    if current is None:
        if sidecar != retired:
            raise invalid()
        return
    if current != original or sidecar is not None and sidecar["witness"] != original.witness:
        raise invalid()
    directory.publish("identity.json", canonical_bytes(retired))
    directory.delete("identity-pending.json")
