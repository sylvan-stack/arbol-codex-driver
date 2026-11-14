"""Read-only verification of the fixed immutable Driver payload.

A declaration describes bytes; it never supplies launch admission or a
qualification verdict. Bootstrap and registry callers must also validate their
live protocol context before reading or changing any Driver state.
"""

import hashlib
import os
import posixpath
import re
import stat
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from .identity_protocol import (
    MANIFEST_ENTRIES,
    MANIFEST_LIMIT,
    PrivateDirectory,
    digest,
    integer,
    invalid,
    object_fields,
    parse_bytes,
    physical_path,
    private_stat,
    relative_path,
    same_inode,
    sha256,
)
from .json_types import Json

MANIFEST = "driver-payload-manifest.json"
DECLARATION = "driver-capability.json"
COMPONENT = "arbol-codex-driver"


@dataclass(frozen=True)
class Entry:
    path: str
    type: str
    mode: int
    size: int
    sha256: str | None
    target: str | None


@dataclass(frozen=True)
class Declaration:
    component: str
    build: str
    commit: str
    tree: str
    interpreter: str
    entry: str
    helpers: tuple[str, ...]
    import_roots: tuple[str, ...]
    manifest_sha256: str
    payload_sha256: str


@dataclass(frozen=True)
class Payload:
    root: Path
    declaration: Declaration
    entries: tuple[Entry, ...]

    def regular_file(self, name: str) -> Path:
        if not any(entry.path == name and entry.type == "file" for entry in self.entries):
            raise invalid()
        return self.root / name


def _text(value: Json) -> str:
    if not isinstance(value, str) or not value:
        raise invalid()
    return value


def _paths(value: Json) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise invalid()
    result = tuple(relative_path(item) for item in value)
    if result != tuple(sorted(set(result), key=lambda item: item.encode("utf-8"))):
        raise invalid()
    return result


def build_number(value: Json) -> str:
    name = _text(value)
    if re.fullmatch(r"[1-9a-f][0-9a-f]*", name) is None:
        raise invalid()
    return name


def _commit(value: Json) -> str:
    name = _text(value)
    if re.fullmatch(r"[0-9a-f]{40}", name) is None:
        raise invalid()
    return name


def _target(value: Json) -> str:
    target = _text(value)
    try:
        target.encode("utf-8", "strict")
    except UnicodeError:
        raise invalid() from None
    if target.startswith("/") or "\\" in target or "\x00" in target:
        raise invalid()
    return target


def _manifest(data: bytes) -> tuple[Entry, ...]:
    value = object_fields(parse_bytes(data, MANIFEST_LIMIT), {"version", "kind", "files"})
    integer(value["version"], 1, 1)
    files = value["files"]
    if value["kind"] != "driver-payload-manifest" or not isinstance(files, list) or len(files) > MANIFEST_ENTRIES:
        raise invalid()
    entries: list[Entry] = []
    normalized: set[str] = set()
    for item in files:
        row = object_fields(item, {"path", "type", "mode", "size", "sha256", "target"})
        path = relative_path(row["path"])
        name = unicodedata.normalize("NFC", path)
        if path in (MANIFEST, DECLARATION) or name in normalized:
            raise invalid()
        normalized.add(name)
        kind = _text(row["type"])
        mode = integer(row["mode"], 0, 4095)
        size = integer(row["size"], 0, (1 << 63) - 1)
        checksum: str | None = None
        target: str | None = None
        if kind == "file":
            checksum = digest(row["sha256"])
            if row["target"] is not None:
                raise invalid()
        elif kind == "directory":
            if size != 0 or row["sha256"] is not None or row["target"] is not None:
                raise invalid()
        elif kind == "symlink":
            target = _target(row["target"])
            checksum = digest(row["sha256"])
            raw = target.encode("utf-8")
            if size != len(raw) or checksum != sha256(raw):
                raise invalid()
        else:
            raise invalid()
        entries.append(Entry(path, kind, mode, size, checksum, target))
    if [entry.path for entry in entries] != sorted(
        (entry.path for entry in entries), key=lambda item: item.encode("utf-8")
    ):
        raise invalid()
    return tuple(entries)


def _file_hash(parent: int, name: str, before: os.stat_result) -> str:
    descriptor = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
    try:
        initial = os.fstat(descriptor)
        if not same_inode(before, initial) or not stat.S_ISREG(initial.st_mode):
            raise invalid()
        result = hashlib.sha256()
        while block := os.read(descriptor, 1024 * 1024):
            result.update(block)
        after = os.fstat(descriptor)
        if (initial.st_size, initial.st_mtime_ns, initial.st_ctime_ns) != (
            after.st_size, after.st_mtime_ns, after.st_ctime_ns
        ):
            raise invalid()
        return result.hexdigest()
    finally:
        os.close(descriptor)


def _inventory(root: PrivateDirectory) -> tuple[Entry, ...]:
    entries: list[Entry] = []

    def walk(parent: int, prefix: str) -> None:
        for name in os.listdir(parent):
            path = relative_path(prefix + name)
            if not prefix and name in (MANIFEST, DECLARATION):
                continue
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
            if info.st_uid != os.getuid() or len(entries) >= MANIFEST_ENTRIES:
                raise invalid()
            mode = stat.S_IMODE(info.st_mode)
            if stat.S_ISDIR(info.st_mode):
                entries.append(Entry(path, "directory", mode, 0, None, None))
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                try:
                    if not same_inode(info, os.fstat(child)):
                        raise invalid()
                    walk(child, path + "/")
                finally:
                    os.close(child)
            elif stat.S_ISREG(info.st_mode):
                entries.append(Entry(path, "file", mode, info.st_size, _file_hash(parent, name, info), None))
            elif stat.S_ISLNK(info.st_mode):
                target = _target(os.readlink(name, dir_fd=parent))
                raw = target.encode("utf-8")
                entries.append(Entry(path, "symlink", mode, len(raw), sha256(raw), target))
            else:
                raise invalid()
            if not same_inode(info, os.stat(name, dir_fd=parent, follow_symlinks=False)):
                raise invalid()

    root.check()
    walk(root.fd, "")
    root.check()
    return tuple(sorted(entries, key=lambda entry: entry.path.encode("utf-8")))


def _links(entries: tuple[Entry, ...]) -> None:
    indexed = {entry.path: entry for entry in entries}
    # Resolve link components without following a host filesystem path.
    def resolve(path: str, active: frozenset[str] = frozenset()) -> str:
        resolved: list[str] = []
        parts = path.split("/")
        for number, part in enumerate(parts):
            if part in ("", "."):
                continue
            if part == "..":
                if not resolved:
                    raise invalid()
                resolved.pop()
                continue
            prefix = "/".join([*resolved, part])
            entry = indexed.get(prefix)
            if entry is None:
                raise invalid()
            if entry.type == "symlink":
                if prefix in active or entry.target is None:
                    raise invalid()
                # Resolve each target before later '..' components, matching
                # filesystem semantics rather than lexical normalization.
                target = posixpath.join("/".join(resolved), entry.target)
                actual = resolve(target, active | {prefix})
                resolved = actual.split("/") if actual else []
                entry = indexed.get(actual) if actual else None
                if number + 1 < len(parts) and entry is not None and entry.type != "directory":
                    raise invalid()
            else:
                if number + 1 < len(parts) and entry.type != "directory":
                    raise invalid()
                resolved.append(part)
        return "/".join(resolved)

    edges: dict[str, list[str]] = {"": []}
    for entry in entries:
        edges.setdefault(posixpath.dirname(entry.path), []).append(entry.path)
        if entry.type == "directory":
            edges.setdefault(entry.path, [])
        elif entry.type == "symlink":
            edges[entry.path] = [resolve(entry.path)]
    active: set[str] = set()
    complete: set[str] = set()

    def visit(path: str) -> None:
        if path in active:
            raise invalid()
        if path in complete:
            return
        active.add(path)
        for child in edges.get(path, []):
            visit(child)
        active.remove(path)
        complete.add(path)

    visit("")


def _declaration(data: bytes, manifest: bytes, entries: tuple[Entry, ...], component: str) -> Declaration:
    value = object_fields(parse_bytes(data), {
        "version", "kind", "component", "build", "source", "interpreter", "entry", "helpers", "importRoots",
        "payloadManifestSha256", "capabilities",
    })
    integer(value["version"], 1, 1)
    if value["kind"] != "driver-capability" or value["component"] != component:
        raise invalid()
    source = object_fields(value["source"], {"commit", "tree"})
    capability = object_fields(value["capabilities"], {"subscriptionIdentity", "driverMaintenance"})
    integer(capability["subscriptionIdentity"], 0 if component == "arbol" else 1, 0 if component == "arbol" else 1)
    integer(capability["driverMaintenance"], 1, 1)
    interpreter, entry = relative_path(value["interpreter"]), relative_path(value["entry"])
    helpers, import_roots = _paths(value["helpers"]), _paths(value["importRoots"])
    indexed = {item.path: item for item in entries}
    for path in (interpreter, entry, *helpers):
        if path not in indexed or indexed[path].type != "file":
            raise invalid()
    if not indexed[interpreter].mode & 0o111:
        raise invalid()
    for path in import_roots:
        if path not in indexed or indexed[path].type not in ("file", "directory"):
            raise invalid()
        if indexed[path].type == "file" and not path.endswith(".zip"):
            raise invalid()
    manifest_hash = digest(value["payloadManifestSha256"])
    if manifest_hash != sha256(manifest):
        raise invalid()
    return Declaration(component, build_number(value["build"]), _commit(source["commit"]), _commit(source["tree"]),
                       interpreter, entry, helpers, import_roots, manifest_hash, sha256(data))


def verify_payload(root: Path, component: str = COMPONENT, *, expected_build: str | None = None) -> Payload:
    if component not in (COMPONENT, "arbol"):
        raise invalid()
    try:
        root = physical_path(str(root))
        with PrivateDirectory(root) as directory:
            manifest = directory.read(MANIFEST, MANIFEST_LIMIT)
            declaration = directory.read(DECLARATION)
            if manifest is None or declaration is None:
                raise invalid()
            entries = _manifest(manifest)
            _links(entries)
            parsed = _declaration(declaration, manifest, entries, component)
            if expected_build is not None and parsed.build != build_number(expected_build):
                raise invalid()
            if _inventory(directory) != entries or _inventory(directory) != entries:
                raise invalid()
            if directory.read(MANIFEST, MANIFEST_LIMIT) != manifest or directory.read(DECLARATION) != declaration:
                raise invalid()
            private_stat(os.fstat(directory.fd), directory=True)
            return Payload(root, parsed, entries)
    except (OSError, ValueError, RuntimeError, RecursionError, UnicodeError):
        raise invalid() from None
