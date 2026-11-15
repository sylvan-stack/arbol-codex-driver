"""Fixed prospective Codex H1 helper. No CLI/gate wiring or library-import I/O."""
from __future__ import annotations

import _imp
import sys

# os and its path implementation must be frozen before any disk import can
# establish an import search path. The pinned qualified CPython supplies them.
if not _imp.is_frozen("os") or not _imp.is_frozen("posixpath"):
    raise SystemExit(1)
import os  # noqa: E402


def refuse() -> None:
    os.write(2, b'{"error":{"code":"internal","message":"Driver admission is unavailable."}}\n')
    raise SystemExit(1)


def confined(root: str, value: str) -> str:
    if not value or not os.path.isabs(value):
        refuse()
    actual = os.path.realpath(value)
    if actual != root and not actual.startswith(root + os.sep):
        refuse()
    return actual


class ActorFailure(ValueError):
    pass


def _require(value: bool, message: str) -> None:
    if not value:
        raise ActorFailure(message)


class _Directory:
    """Existing private physical directories; this actor never creates a namespace."""

    def __init__(self, path: Path, descriptor: int):
        import stat

        self.path, self.descriptor = path, descriptor
        info = os.fstat(descriptor)
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o700, "Unsafe actor fixture directory.")
        self.identity = (info.st_dev, info.st_ino)
        self.verify()

    @classmethod
    def root(cls, path: Path) -> _Directory:
        _require(path.is_absolute() and path.resolve(strict=True) == path, "Actor registry is not physical.")
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            return cls(path, descriptor)
        except BaseException:
            os.close(descriptor)
            raise

    def verify(self) -> None:
        import stat

        info, named = os.fstat(self.descriptor), self.path.lstat()
        _require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.getuid()
                 and stat.S_IMODE(info.st_mode) == 0o700
                 and (info.st_dev, info.st_ino) == self.identity == (named.st_dev, named.st_ino),
                 "Actor fixture directory changed.")

    def existing(self, name: str) -> _Directory:
        _require(bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name,
                 "Invalid actor namespace component.")
        self.verify()
        descriptor = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                             dir_fd=self.descriptor)
        try:
            result = _Directory(self.path / name, descriptor)
            named = os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
            _require(result.identity == (named.st_dev, named.st_ino), "Actor child directory changed.")
            self.verify()
            return result
        except BaseException:
            os.close(descriptor)
            raise

    def read(self, name: str, *, limit: int = 4096) -> bytes:
        import stat

        _require(bool(name) and name not in (".", "..") and "/" not in name and "\\" not in name,
                 "Invalid actor evidence name.")
        self.verify()
        descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                             dir_fd=self.descriptor)
        try:
            before = os.fstat(descriptor)
            _require(stat.S_ISREG(before.st_mode) and before.st_uid == os.getuid()
                     and stat.S_IMODE(before.st_mode) == 0o600 and before.st_nlink == 1 and before.st_size <= limit,
                     "Unsafe actor fixture evidence.")
            raw = bytearray()
            while len(raw) <= limit:
                part = os.read(descriptor, min(65536, limit + 1 - len(raw)))
                if not part:
                    break
                raw.extend(part)
            after, named = os.fstat(descriptor), os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
            _require(len(raw) <= limit and after.st_nlink == 1
                     and (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns,
                          before.st_uid, before.st_mode) ==
                         (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_uid, after.st_mode)
                     and (after.st_dev, after.st_ino) == (named.st_dev, named.st_ino),
                     "Actor fixture evidence changed.")
            self.verify()
            return bytes(raw)
        finally:
            os.close(descriptor)

    def exclusive(self, name: str, raw: bytes) -> None:
        import stat

        _require(name == "h1-capture.json" and 0 < len(raw) <= 4096, "Invalid fixed capture observation.")
        self.verify()
        descriptor = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                             0o600, dir_fd=self.descriptor)
        try:
            view = memoryview(raw)
            while view:
                written = os.write(descriptor, view)
                _require(written > 0, "Actor capture write made no progress.")
                view = view[written:]
            os.fsync(descriptor)
            info, named = os.fstat(descriptor), os.stat(name, dir_fd=self.descriptor, follow_symlinks=False)
            _require(stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid()
                     and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
                     and (info.st_dev, info.st_ino) == (named.st_dev, named.st_ino), "Actor capture name changed.")
            os.fsync(self.descriptor)
            self.verify()
        finally:
            os.close(descriptor)

    def close(self) -> None:
        if self.descriptor >= 0:
            descriptor, self.descriptor = self.descriptor, -1
            os.close(descriptor)


def _bootstrap() -> int:
    if not (
        sys.flags.isolated and sys.flags.no_site and sys.flags.ignore_environment
        and sys.flags.dont_write_bytecode and sys.flags.safe_path
    ):
        refuse()
    script = os.path.abspath(__file__)
    if script != os.path.realpath(script):
        refuse()
    root = os.path.dirname(os.path.dirname(script))
    if os.path.basename(root) != "driver-payload":
        refuse()
    executable = confined(root, sys.executable)
    for prefix in (sys.prefix, sys.exec_prefix, sys.base_prefix, sys.base_exec_prefix):
        confined(root, prefix)
    for path in sys.path:
        confined(root, path)
    for module in tuple(sys.modules.values()):
        module_file = getattr(module, "__file__", None)
        if module_file is not None:
            confined(root, module_file)
    info = os.stat(root, follow_symlinks=False)
    if info.st_uid != os.getuid() or info.st_mode & 0o7777 != 0o700 or info.st_mode & 0o170000 != 0o040000:
        refuse()
    # Only confined bundled standard library imports are permitted at this
    # stage. The admitted parent already verified these exact payload bytes.
    import json

    descriptor = os.open(os.path.join(root, "driver-capability.json"), os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        info = os.fstat(descriptor)
        if info.st_uid != os.getuid() or info.st_mode & 0o7777 != 0o600 or info.st_mode & 0o170000 != 0o100000:
            refuse()
        raw = bytearray()
        while len(raw) <= 4096:
            part = os.read(descriptor, 4097 - len(raw))
            if not part:
                break
            raw.extend(part)
        if not raw or len(raw) > 4096:
            refuse()
    finally:
        os.close(descriptor)

    def pairs(items: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in items:
            if key in result:
                refuse()
            result[key] = value
        return result

    value = json.loads(bytes(raw).decode("utf-8", "strict"), object_pairs_hook=pairs)
    fields = {
        "version", "kind", "component", "build", "source", "interpreter", "entry", "helpers", "importRoots",
        "payloadManifestSha256", "capabilities",
    }
    if (
        not isinstance(value, dict) or set(value) != fields or type(value["version"]) is not int or value["version"] != 1
        or value["kind"] != "driver-capability" or value["component"] != "arbol-codex-driver"
        or (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n")
        .encode("utf-8", "strict") != raw
    ):
        refuse()

    def relative(name: object) -> str:
        if not isinstance(name, str) or "\\" in name or "\x00" in name or any(
            part in ("", ".", "..") for part in name.split("/")
        ):
            refuse()
        assert isinstance(name, str)
        path = os.path.join(root, name)
        if confined(root, path) != path or not os.path.exists(path):
            refuse()
        return path

    if relative(value["interpreter"]) != executable:
        refuse()
    helpers, roots = value["helpers"], value["importRoots"]
    if not isinstance(helpers, list) or not isinstance(roots, list) or not roots:
        refuse()
    entries = [relative(value["entry"]), *(relative(item) for item in helpers)]
    if script not in entries or roots != sorted(set(roots), key=lambda item: item.encode("utf-8")):
        refuse()
    sys.path[:] = [relative(item) for item in roots]
    return _run_admitted(root, script, bytes(raw))


def _lease_hold(session: Session, channel: Socket, case: str) -> None:
    """Real wrapper return precedes the H1 wait; no later Subscription work."""
    import asyncio
    import socket
    import time
    from pathlib import Path

    from arbol_codex_driver.identity_protocol import canonical_bytes, object_fields, parse_bytes, token
    from arbol_codex_driver.state import State
    from arbol_codex_driver.subscriptions import Subscriptions

    context = session.context
    session._check()
    _require(context["role"] == "helper" and context["entry"] == "tests/identity_actor.py"
             and context["component"] == "arbol-codex-driver", "Wrong actual helper context.")
    opened: list[_Directory] = []
    state: State | None = None
    original: BaseException | None = None
    try:
        current = _Directory.root(Path(str(context["registry"])))
        opened.append(current)
        for name in (".driver-qualification", "fixtures", token(context["invocation"]), case):
            current = current.existing(name)
            opened.append(current)
        fixture = current
        marker = object_fields(parse_bytes(fixture.read(".fixture-owner.json")),
                               {"version", "case", "component", "invocation", "parentWriter", "payloadSha256"})
        parent = context["parent"]
        _require(isinstance(parent, dict), "Invalid actual helper parent.")
        assert isinstance(parent, dict)
        _require(marker == {"version": 1, "case": case, "component": "arbol-codex-driver",
            "invocation": context["invocation"], "parentWriter": parent["writer"],
            "payloadSha256": session.authority.producer.declaration.payload_sha256}
            and type(marker["version"]) is int, "Wrong actual fixture owner.")
        local = fixture.existing("state")
        opened.append(local)
        vendor = fixture.existing("vendor")
        opened.append(vendor)
        _require(local.read("format") == b"2\n", "H1 needs its genuinely prepared local format-two State.")
        state = State(local.path)
        state.initialize()
        identity = state.assert_admitted()
        _require(channel.fileno() not in (session.lease, identity.descriptor), "Control aliases a held admission/guard.")
        subscriptions = Subscriptions(state, {}, [], vendor.path / "settings.json", {})
        proof = asyncio.run(subscriptions.identity("chatgpt"))
        proof = object_fields(proof, {"version", "driver", "subscription", "generation", "witness"})
        _require(type(proof["version"]) is int and proof["version"] == 1 and proof["driver"] == "codex"
                 and proof["subscription"] == "chatgpt", "Real wrapper returned another proof.")
        token(proof["generation"])
        token(proof["witness"])
        fixture.exclusive("h1-capture.json", canonical_bytes(proof))
        # asyncio.run has closed/joined its loop; with_subscription_lock has
        # already exited/unlinked its ephemeral lock. Only admission/guard remain.
        ready = canonical_bytes({"version": 1, "kind": "actor-ready", "case": case,
                                 "action": "lease-hold", "window": "H1-independent-lease"})
        deadline = time.monotonic() + 10
        channel.settimeout(max(.001, deadline - time.monotonic()))
        channel.sendall(ready)
        raw = bytearray()
        while b"\n" not in raw:
            remaining = deadline - time.monotonic()
            _require(remaining > 0, "H1 control exceeded its10s lifetime.")
            channel.settimeout(remaining)
            part = channel.recv(4097 - len(raw))
            _require(bool(part), "Parent EOF is failed control, never completion.")
            raw.extend(part)
            _require(len(raw) <= 4096, "H1 control overflow.")
        reply = object_fields(parse_bytes(bytes(raw)), {"version", "kind", "case", "command"})
        _require(reply == {"version": 1, "kind": "actor-control", "case": case, "command": "continue"}
                 and type(reply["version"]) is int and canonical_bytes(reply) == raw,
                 "H1 accepts exactly its own single canonical continue.")
        channel.setblocking(False)
        try:
            _require(not channel.recv(1, socket.MSG_PEEK), "Extra parent control bytes.")
        except BlockingIOError:
            pass
        # No State/Subscription operation follows this wait, including on EOF.
    except BaseException as error:
        original = error
        raise
    finally:
        failures: list[BaseException] = []
        if state is not None:
            try:
                state.close()
            except BaseException as error:
                failures.append(error)
        for directory in reversed(opened):
            try:
                directory.close()
            except BaseException as error:
                failures.append(error)
        try:
            channel.close()
        except BaseException as error:
            failures.append(error)
        if failures:
            if original is not None:
                for cleanup_error in failures:
                    original.add_note("H1 local cleanup: " + type(cleanup_error).__name__)
            else:
                raise BaseExceptionGroup("H1 local cleanup failed.", failures)


def _run_admitted(root: str, script: str, declaration_raw: bytes) -> int:
    """The unmodified real normal wire owns the only Session/terminal lifecycle."""
    import re
    import signal
    import socket
    from pathlib import Path

    from arbol_codex_driver.admission import AUTHORITY_ENV, NORMAL_CONTEXT, NORMAL_FD, admit
    from arbol_codex_driver.identity_protocol import PrivateDirectory, canonical_bytes
    from arbol_codex_driver.payload import verify_payload

    payload = verify_payload(Path(root))
    # The manifest/declaration exclude themselves from M's inventory; use the
    # real private declaration read, not regular_file's M-entry-only selector.
    with PrivateDirectory(payload.root) as directory:
        observed_declaration = directory.read("driver-capability.json")
    _require(observed_declaration == declaration_raw
             and script == str(payload.root / "tests/identity_actor.py")
             and "tests/identity_actor.py" in payload.declaration.helpers
             and os.path.realpath(sys.executable) == str(payload.root / payload.declaration.interpreter),
             "Wrong complete runtime/M-D/helper entry.")
    _require(len(sys.argv) == 6, "H1 accepts exactly five positional arguments.")
    action, selector, window, case, control = sys.argv[1:]
    _require((action, selector, window) == ("lease-hold", "chatgpt", "H1-independent-lease")
             and re.fullmatch(r"[0-9a-f]{32}", case, re.ASCII) is not None
             and re.fullmatch(r"[1-9][0-9]{0,4}", control, re.ASCII) is not None
             and 3 <= int(control) <= 65535, "Unsupported fixed H1 grammar.")
    _require({key for key in AUTHORITY_ENV if key in os.environ} == {NORMAL_FD, NORMAL_CONTEXT},
             "H1 needs exactly the real normal admission pair.")
    fd_text, path_text = os.environ[NORMAL_FD], os.environ[NORMAL_CONTEXT]
    _require(re.fullmatch(r"[1-9][0-9]*", fd_text, re.ASCII) is not None
             and 3 <= int(fd_text) <= 2**31 - 1 and str(int(fd_text)) == fd_text
             and int(control) != int(fd_text), "Control/admission descriptions overlap or are invalid.")
    context = Path(path_text)
    _require(context.is_absolute() and str(context) == path_text
             and os.path.realpath(context.parent) == str(context.parent), "Unconfined normal context path.")
    for name in AUTHORITY_ENV:
        os.environ.pop(name, None)
    channel: socket.socket | None = socket.socket(fileno=int(control))
    session: Session | None = None
    body_started = False

    def expired(number: int, frame: FrameType | None) -> None:
        raise TimeoutError("Fixed H1 actor lifetime expired.")

    prior = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, 120)
    try:
        assert channel is not None
        _require(channel.family == socket.AF_UNIX and channel.type == socket.SOCK_STREAM,
                 "H1 control is not an AF_UNIX stream.")
        channel.getpeername()
        channel.set_inheritable(False)
        session = admit(payload, context, int(fd_text))
        _require(channel.fileno() != session.lease, "H1 control aliases its independently opened lease.")
        with session:
            body_started = True
            try:
                _lease_hold(session, channel, case)
                channel = None
                result = canonical_bytes({"version": 1, "kind": "actor-result", "case": case,
                                          "action": "lease-hold", "outcome": "completed"})
                _require(os.write(1, result) == len(result), "Incomplete final H1 output.")
            except BaseException:
                # Output BEFORE real abandon/lease-close. Re-raise through the
                # REAL Session context, so EOF/error cannot become false terminal.
                result = canonical_bytes({"version": 1, "kind": "actor-result", "case": case,
                                          "action": "lease-hold", "outcome": "refused"})
                os.write(1, result)
                os.write(2, b"H1 action failed; retain actual custody and private evidence.\n")
                raise
        return 0  # Exactly one genuine context-manager finish, no manual finish.
    except BaseException as original:
        if not body_started:
            os.write(2, b"H1 admission unavailable; retain its real failed evidence.\n")
        if session is not None and session.lease >= 0:
            # A failure after real admit but before __enter__ still owns real
            # custody. Abandon THAT object; never silently drop the live lease
            # or synthesize a terminal. Normal with-session failures already
            # performed this real path and have lease=-1.
            try:
                session.abandon()
            except BaseException as cleanup_error:
                original.add_note("Actual admission abandon: " + type(cleanup_error).__name__)
        return 1 if body_started else 2
    finally:
        if channel is not None:
            channel.close()
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, prior)


if __name__ == "__main__":
    try:
        raise SystemExit(_bootstrap())
    except SystemExit:
        raise
    except BaseException:
        os.write(2, b"H1 helper requires its isolated immutable payload and normal admission.\n")
        raise SystemExit(2) from None
else:
    # Types/library imports are unreachable on the standalone pre-admission path.
    from pathlib import Path
    from socket import socket as Socket
    from types import FrameType

    from arbol_codex_driver.admission import Session
