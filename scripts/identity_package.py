"""Static immutable payload inventory/emission; never admission or acceptance.

Called only after executable/provenance bytes settle in a registered Build.
No product imports, runtime probes, source execution or qualification occurs.
"""

from __future__ import annotations

import hashlib
import json
import os
import posixpath
import re
import stat
import unicodedata
from pathlib import Path
from typing import Any

from build_support import BUILD_NUMBER, COMPONENT, IDENTITY_METADATA, PAYLOAD

MANIFEST = "driver-payload-manifest.json"
DECLARATION = "driver-capability.json"
MAXIMUM = 32 * 1024 * 1024
ENTRIES = 100000
INTERPRETER = "runtime/python/bin/python3.14"
ENTRY = "bin/entry.py"
# Reserved exact files; ABR-38 must author/admit runner/actor bodies before use.
HELPERS = [ENTRY, "scripts/check_build.py", "tests/identity_actor.py"]
IMPORT_ROOTS = ["runtime/python/lib/python3.14", "runtime/python/lib/python3.14/lib-dynload", "src"]


def canonical(value: object, limit: int = MAXIMUM) -> bytes:
    data = (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(",", ":")) + "\n").encode(
        "utf-8", "strict",
    )
    if len(data) > limit:
        raise ValueError("Immutable metadata exceeds its protocol bound.")
    return data


def relative(value: str) -> str:
    value.encode("utf-8", "strict")
    if not value or "\\" in value or "\0" in value or any(part in ("", ".", "..") for part in value.split("/")):
        raise ValueError("Unsafe immutable payload path.")
    return value


def same(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino, left.st_size, left.st_mtime_ns, left.st_ctime_ns, left.st_mode) == (
        right.st_dev, right.st_ino, right.st_size, right.st_mtime_ns, right.st_ctime_ns, right.st_mode,
    )


def inventory(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    normalized: set[str] = set()
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        root_info = os.fstat(descriptor)
        if (root_info.st_uid != os.getuid() or stat.S_IMODE(root_info.st_mode) != 0o700
                or root.resolve(strict=True) != root or not same(root_info, root.lstat())):
            raise ValueError("Payload root must be a canonical private directory.")

        def visit(parent: int, prefix: str) -> None:
            for name in os.listdir(parent):
                if not prefix and name in IDENTITY_METADATA:
                    continue  # Exactly these two root metadata files, no subtree.
                path = relative(prefix + name)
                key = unicodedata.normalize("NFC", path)
                if key in normalized or len(rows) >= ENTRIES:
                    raise ValueError("Duplicate/normalized payload path or inventory bound exceeded.")
                normalized.add(key)
                info = os.stat(name, dir_fd=parent, follow_symlinks=False)
                if info.st_uid != os.getuid():
                    raise ValueError("Payload contains a foreign owner.")
                row: dict[str, Any] = {"path": path, "type": "", "mode": stat.S_IMODE(info.st_mode),
                                       "size": 0, "sha256": None, "target": None}
                if stat.S_ISDIR(info.st_mode):
                    row["type"] = "directory"
                    rows.append(row)
                    child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=parent)
                    try:
                        if not same(info, os.fstat(child)):
                            raise ValueError("Payload directory changed during inventory.")
                        visit(child, path + "/")
                    finally:
                        os.close(child)
                elif stat.S_ISREG(info.st_mode):
                    child = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC, dir_fd=parent)
                    try:
                        if not same(info, os.fstat(child)) or info.st_size < 0 or info.st_size >= 1 << 63:
                            raise ValueError("Payload file changed or has an unsupported size.")
                        checksum = hashlib.sha256()
                        while part := os.read(child, 1024 * 1024):
                            checksum.update(part)
                        if not same(info, os.fstat(child)):
                            raise ValueError("Payload file changed during hashing.")
                    finally:
                        os.close(child)
                    row.update(type="file", size=info.st_size, sha256=checksum.hexdigest())
                    rows.append(row)
                elif stat.S_ISLNK(info.st_mode):
                    target = os.readlink(name, dir_fd=parent)
                    raw = target.encode("utf-8", "strict")
                    if not target or target.startswith("/") or "\\" in target or "\0" in target:
                        raise ValueError("Payload links must be relative and confined.")
                    row.update(type="symlink", target=target, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                    rows.append(row)
                else:
                    raise ValueError("Special files cannot enter an immutable payload.")
                if not same(info, os.stat(name, dir_fd=parent, follow_symlinks=False)):
                    raise ValueError("Payload entry changed during inventory.")

        visit(descriptor, "")
        if not same(root_info, root.lstat()):
            raise ValueError("Payload root changed during inventory.")
    finally:
        os.close(descriptor)
    return sorted(rows, key=lambda row: str(row["path"]).encode("utf-8"))


def validate_links(rows: list[dict[str, Any]]) -> None:
    indexed = {str(row["path"]): row for row in rows}

    def resolve(path: str, active: frozenset[str] = frozenset()) -> str:
        parts = path.split("/")
        resolved: list[str] = []
        for index, part in enumerate(parts):
            if part in ("", "."):
                continue
            if part == "..":
                if not resolved:
                    raise ValueError("Payload link escapes its root.")
                resolved.pop()
                continue
            current = "/".join([*resolved, part])
            row = indexed.get(current)
            if row is None:
                raise ValueError("Dangling payload link.")
            if row["type"] == "symlink":
                if current in active:
                    raise ValueError("Cyclic payload link.")
                target = posixpath.join("/".join(resolved), str(row["target"]))
                actual = resolve(target, active | {current})
                resolved = actual.split("/") if actual else []
                destination = indexed.get(actual) if actual else None
                if index < len(parts) - 1 and destination is not None and destination["type"] != "directory":
                    raise ValueError("Payload link traverses a regular file.")
            else:
                if index < len(parts) - 1 and row["type"] != "directory":
                    raise ValueError("Payload link traverses a regular file.")
                resolved.append(part)
        return "/".join(resolved)

    graph: dict[str, list[str]] = {"": []}
    for row in rows:
        path = str(row["path"])
        graph.setdefault(posixpath.dirname(path), []).append(path)
        if row["type"] == "directory":
            graph.setdefault(path, [])
        elif row["type"] == "symlink":
            graph[path] = [resolve(path)]
    active: set[str] = set()
    complete: set[str] = set()

    def visit(path: str) -> None:
        if path in active:
            raise ValueError("Payload directory/link graph is cyclic.")
        if path in complete:
            return
        active.add(path)
        for child in graph.get(path, []):
            visit(child)
        active.remove(path)
        complete.add(path)

    visit("")


def write_new(root: Path, name: str, data: bytes) -> None:
    descriptor = os.open(root / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        view = memoryview(data)
        while view:
            count = os.write(descriptor, view)
            if count <= 0:
                raise OSError("Incomplete immutable metadata publication.")
            view = view[count:]
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        os.fsync(parent)
    finally:
        os.close(parent)


def emit(root: Path, build: str, source: dict[str, Any]) -> None:
    if root.name != PAYLOAD or not BUILD_NUMBER.fullmatch(build):
        raise ValueError("Only an exact registered Build can emit final identity declarations.")
    commit, tree = source.get("commit"), source.get("tree")
    if (source.get("uncommittedChanges") is not False or not isinstance(commit, str) or not isinstance(tree, str)
            or re.fullmatch(r"[0-9a-f]{40}", commit) is None or re.fullmatch(r"[0-9a-f]{40}", tree) is None):
        raise ValueError("Final identity declarations require exact clean committed source.")
    if any(os.path.lexists(root / name) for name in IDENTITY_METADATA):
        raise ValueError("Refusing to replace immutable identity metadata.")
    rows = inventory(root)
    validate_links(rows)
    indexed = {str(row["path"]): row for row in rows}
    for name in (INTERPRETER, ENTRY, *HELPERS):
        if name not in indexed or indexed[name]["type"] != "file":
            raise ValueError("Declared interpreter and entry must be inventoried regular files.")
    if not indexed[INTERPRETER]["mode"] & 0o111:
        raise ValueError("Pinned interpreter is not executable.")
    for name in IMPORT_ROOTS:
        if name not in indexed or indexed[name]["type"] != "directory":
            raise ValueError("Every exact import root must be present in the complete inventory.")
    manifest = canonical({"version": 1, "kind": "driver-payload-manifest", "files": rows})
    declaration = canonical({
        "version": 1, "kind": "driver-capability", "component": COMPONENT, "build": build,
        "source": {"commit": commit, "tree": tree}, "interpreter": INTERPRETER, "entry": ENTRY,
        "helpers": HELPERS, "importRoots": IMPORT_ROOTS,
        "payloadManifestSha256": hashlib.sha256(manifest).hexdigest(),
        "capabilities": {"subscriptionIdentity": 1, "driverMaintenance": 1},
    }, 4096)
    if inventory(root) != rows:
        raise ValueError("Payload changed before immutable metadata publication.")
    write_new(root, MANIFEST, manifest)
    write_new(root, DECLARATION, declaration)
    if inventory(root) != rows:
        raise ValueError("Payload changed during immutable metadata publication.")
