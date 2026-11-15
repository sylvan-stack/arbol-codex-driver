"""Immutable metadata-only maintenance archives, never live admission authority.

Call preservation only under verified component maintenance and the stable
exclusive local guard. No record, credential, vendor home, chat or guard bytes
belong here. Failed bounded bytes remain evidence; source validation is separate.
"""

import os
import stat
from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .identity import PendingIdentity, canonical_id
from .identity_protocol import (
    MANIFEST_ENTRIES,
    MANIFEST_LIMIT,
    PrivateDirectory,
    canonical_bytes,
    canonical_uuid,
    digest,
    integer,
    invalid,
    object_fields,
    parse_bytes,
    private_stat,
    sha256,
    token,
)
from .json_types import Json, Object
from .payload import COMPONENT

ROOT_METADATA = ("format", "identity.json", "identity-maintenance.json", "identity-upgrade.json")
OPERATIONS = ("upgrade", "identity-reset", "restore", "identity-recover")


def sync_directory(path: Path) -> None:
    with PrivateDirectory(path) as directory:
        directory.check()
        os.fsync(directory.fd)


def private_directory(path: Path, *, create: bool = False) -> Path:
    if create:
        with PrivateDirectory(path.parent):
            try:
                path.mkdir(mode=0o700)
                sync_directory(path.parent)
            except FileExistsError:
                pass
    with PrivateDirectory(path):
        pass
    return path


def metadata_name(value: Json) -> str:
    if not isinstance(value, str):
        raise invalid()
    if value in ROOT_METADATA:
        return value
    parts = value.split("/")
    if len(parts) != 3 or parts[0] != "subscriptions" or parts[2] not in ("identity.json", "identity-pending.json"):
        raise invalid()
    canonical_id(parts[1])
    return value


def metadata_names(directory: Path, extra: list[str] | None = None) -> list[str]:
    private_directory(directory)
    names = set(ROOT_METADATA)
    for value in extra or []:
        name = metadata_name(value)
        names.add(name)
        if name.startswith("subscriptions/"):
            prefix = name.rsplit("/", 1)[0]
            names.update(prefix + "/" + leaf for leaf in ("identity.json", "identity-pending.json"))
    subscriptions = directory / "subscriptions"
    if os.path.lexists(subscriptions):
        private_directory(subscriptions)
        for entry in subscriptions.iterdir():
            canonical_id(entry.name)
            private_directory(entry)
            names.update(f"subscriptions/{entry.name}/{leaf}" for leaf in ("identity.json", "identity-pending.json"))
            if len(names) > MANIFEST_ENTRIES:
                raise invalid()
    if len(names) > MANIFEST_ENTRIES:
        raise invalid()
    return sorted(names, key=lambda value: value.encode("utf-8"))


def read_bytes(path: Path, *, limit: int = MANIFEST_LIMIT) -> bytes | None:
    if not path.is_absolute():
        raise invalid()
    # Explicit absence includes a source-only Subscription whose current
    # directory does not exist. Walk with no-follow descriptors first because
    # PrivateDirectory's physical-path validator deliberately folds a missing
    # parent into its general unsafe-path refusal. Never swallow that refusal.
    descriptor = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
    try:
        for part in path.parent.parts[1:]:
            try:
                following = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                                    dir_fd=descriptor)
            except FileNotFoundError:
                return None
            os.close(descriptor)
            descriptor = following
    finally:
        os.close(descriptor)
    with PrivateDirectory(path.parent) as directory:
        return directory.read(path.name, limit=limit)


def publish_bytes(path: Path, data: bytes, *, limit: int = MANIFEST_LIMIT) -> None:
    with PrivateDirectory(path.parent) as directory:
        directory.publish(path.name, data, limit=limit)


def raw_format(data: bytes | None) -> int | None:
    return {b"1": 1, b"2": 2}.get(data.strip()) if data is not None else None


def local_marker(value: Json) -> Object:
    row = object_fields(value, {
        "version", "component", "session", "epoch", "operation", "attempt", "payloadSha256", "generation", "phase",
        "sourceSha256", "backupSha256",
    })
    integer(row["version"], 1, 1)
    if row["component"] != COMPONENT or row["operation"] not in OPERATIONS or row["phase"] not in ("pending", "complete"):
        raise invalid()
    canonical_uuid(row["session"])
    for name in ("epoch", "attempt", "generation"):
        token(row[name])
    for name in ("payloadSha256", "backupSha256"):
        digest(row[name])
    if row["sourceSha256"] is not None:
        digest(row["sourceSha256"])
    if (row["operation"] == "restore") != (row["sourceSha256"] is not None):
        raise invalid()
    return row


def validate_source(name: str, raw: bytes) -> None:
    if name == "format":
        return
    value = parse_bytes(raw)
    if name == "identity-maintenance.json":
        local_marker(value)
    elif name.endswith("/identity-pending.json"):
        if not isinstance(value, dict):
            raise invalid()
        PendingIdentity.parse(value)
    elif name.endswith("/identity.json"):
        row = object_fields(value, {"version", "witness", "state"})
        integer(row["version"], 1, 1)
        token(row["witness"])
        if row["state"] not in ("active", "retired"):
            raise invalid()
    elif name == "identity.json":
        row = object_fields(value, {"version", "generation"})
        integer(row["version"], 1, 1)
        token(row["generation"])
    else:
        row = object_fields(value, {"version", "from", "to", "generation", "backup", "backupSha256"})
        integer(row["version"], 1, 1)
        integer(row["from"], 1, 1)
        integer(row["to"], 2, 2)
        token(row["generation"])
        digest(row["backupSha256"])
        path = row["backup"]
        if not isinstance(path, str) or not Path(path).is_absolute() or os.path.normpath(path) != path or "\0" in path:
            raise invalid()


@dataclass(frozen=True)
class Entry:
    path: str
    present: bool
    size: int
    sha256: str | None

    @classmethod
    def parse(cls, value: Json) -> Entry:
        row = object_fields(value, {"path", "present", "size", "sha256"})
        name, size = metadata_name(row["path"]), integer(row["size"], 0, MANIFEST_LIMIT)
        present = row["present"]
        if type(present) is not bool:
            raise invalid()
        checksum = digest(row["sha256"]) if present else None
        if not present and (size != 0 or row["sha256"] is not None):
            raise invalid()
        return cls(name, present, size, checksum)

    def document(self) -> Object:
        return {"path": self.path, "present": self.present, "size": self.size, "sha256": self.sha256}


@dataclass(frozen=True)
class Archive:
    directory: Path
    format: int | None
    entries: tuple[Entry, ...]
    digest: str

    @classmethod
    def load(cls, directory: Path, *, source: bool = False) -> Archive:
        private_directory(directory)
        raw = read_bytes(directory / "manifest.json")
        if raw is None:
            raise invalid()
        manifest = object_fields(parse_bytes(raw, MANIFEST_LIMIT), {"version", "kind", "format", "files"})
        integer(manifest["version"], 1, 1)
        if manifest["kind"] != "driver-identity-backup":
            raise invalid()
        number = integer(manifest["format"], 1, 2) if manifest["format"] is not None else None
        rows = manifest["files"]
        if not isinstance(rows, list) or len(rows) > MANIFEST_ENTRIES:
            raise invalid()
        entries = tuple(Entry.parse(row) for row in rows)
        names = [entry.path for entry in entries]
        name_set = set(names)
        if names != sorted(name_set, key=lambda value: value.encode("utf-8")) or not set(ROOT_METADATA).issubset(names):
            raise invalid()
        expected = {"manifest.json"}
        total = len(raw)
        for entry in entries:
            if entry.path.startswith("subscriptions/"):
                prefix = entry.path.rsplit("/", 1)[0]
                if any(prefix + "/" + leaf not in name_set for leaf in ("identity.json", "identity-pending.json")):
                    raise invalid()
            content = read_bytes(directory / entry.path, limit=MANIFEST_LIMIT - total)
            if not entry.present:
                if content is not None:
                    raise invalid()
                continue
            if content is None or len(content) != entry.size or sha256(content) != entry.sha256:
                raise invalid()
            total += len(content)
            expected.add(entry.path)
            expected.update("/".join(entry.path.split("/")[:index]) for index in range(1, len(entry.path.split("/"))))
            if source:
                validate_source(entry.path, content)
        actual: set[str] = set()
        for folder, directories, files in os.walk(directory, followlinks=False):
            for name in (*directories, *files):
                path = Path(folder) / name
                relative = path.relative_to(directory).as_posix()
                if relative not in expected:
                    raise invalid()
                actual.add(relative)
                info = path.lstat()
                private_stat(info, directory=stat.S_ISDIR(info.st_mode))
        result = cls(directory, number, entries, sha256(raw))
        if actual != expected or raw_format(result.content("format")) != number:
            raise invalid()
        if source and (number not in (1, 2) or len(result.content("format") or b"") > 4096 or number == 2 and (
            result.content("identity.json") is None or result.content("format") != b"2\n"
        )):
            raise invalid()
        return result

    @cached_property
    def rows(self) -> dict[str, Entry]:
        return {entry.path: entry for entry in self.entries}

    @property
    def manifest(self) -> Object:
        return {"version": 1, "kind": "driver-identity-backup", "format": self.format,
                "files": [entry.document() for entry in self.entries]}

    def content(self, name: str) -> bytes | None:
        entry = self.rows.get(metadata_name(name))
        if entry is None or not entry.present:
            return None
        raw = read_bytes(self.directory / name)
        if raw is None or len(raw) != entry.size or sha256(raw) != entry.sha256:
            raise invalid()
        return raw


def snapshot(directory: Path, names: list[str]) -> dict[str, bytes | None]:
    if names != metadata_names(directory, names):
        raise invalid()
    result: dict[str, bytes | None] = {}
    total = 0
    for name in names:
        raw = read_bytes(directory / metadata_name(name), limit=MANIFEST_LIMIT - total)
        result[name] = raw
        total += len(raw) if raw is not None else 0
    return result


def archive_parent(directory: Path, name: str) -> None:
    current = directory
    for part in metadata_name(name).split("/")[:-1]:
        current = private_directory(current / part, create=True)


def entry_manifest(data: dict[str, bytes | None]) -> Object:
    name_set = set(ROOT_METADATA) | set(data)
    for name in data:
        metadata_name(name)
        if name.startswith("subscriptions/"):
            prefix = name.rsplit("/", 1)[0]
            name_set.update(prefix + "/" + leaf for leaf in ("identity.json", "identity-pending.json"))
    names = sorted(name_set, key=lambda value: value.encode("utf-8"))
    if len(names) > MANIFEST_ENTRIES:
        raise invalid()
    rows: list[Json] = []
    total = 0
    for name in names:
        metadata_name(name)
        raw = data.get(name)
        total += len(raw) if raw is not None else 0
        rows.append(Entry(name, raw is not None, len(raw) if raw is not None else 0,
                          sha256(raw) if raw is not None else None).document())
    manifest: Object = {"version": 1, "kind": "driver-identity-backup", "format": raw_format(data.get("format")), "files": rows}
    if total + len(canonical_bytes(manifest, MANIFEST_LIMIT)) > MANIFEST_LIMIT:
        raise invalid()
    return manifest


def _write_entry(destination: Path, data: dict[str, bytes | None], manifest: Object) -> Archive:
    private_directory(destination, create=True)
    manifest_bytes = canonical_bytes(manifest, MANIFEST_LIMIT)
    if os.path.lexists(destination / "manifest.json"):
        result = Archive.load(destination)
        if result.digest != sha256(manifest_bytes):
            raise invalid()
        return result
    for name, raw in data.items():
        if raw is None:
            continue
        archive_parent(destination, name)
        previous = read_bytes(destination / name)
        if previous is None:
            publish_bytes(destination / name, raw)
        elif previous != raw:
            raise invalid()
    # PrivateDirectory's exact interrupted writer names are retained outside
    # the immutable entry. Unknown bytes never disappear into an exclusion.
    for folder, _, files in os.walk(destination, followlinks=False):
        for name in files:
            if not name.startswith(".write-identity-"):
                continue
            token(name.removeprefix(".write-identity-"))
            path = Path(folder) / name
            raw = read_bytes(path)
            if raw is None:
                raise invalid()
            evidence = private_directory(destination.parent / "staging-evidence", create=True)
            target = evidence / sha256(path.relative_to(destination).as_posix().encode("utf-8"))
            if os.path.lexists(target):
                raise invalid()
            os.rename(path, target)
            sync_directory(path.parent)
            sync_directory(evidence)
    publish_bytes(destination / "manifest.json", manifest_bytes)
    return Archive.load(destination)


def preserve_entry(destination: Path, data: dict[str, bytes | None]) -> Archive:
    """Internal conversion/abandoned metadata entry; caller retains authority."""
    return _write_entry(destination, data, entry_manifest(data))


def preserve(directory: Path, destination: Path, context: Object, source_hash: str | None,
             *, extra: list[str] | None = None) -> Archive:
    private_directory(directory)
    private_directory(destination)
    if directory.is_relative_to(destination) or destination.is_relative_to(directory):
        raise invalid()
    if source_hash is not None:
        digest(source_hash)
    binding: Object = {"version": 1, "kind": "driver-identity-preservation", "component": COMPONENT,
                       "session": canonical_uuid(context["session"]), "epoch": token(context["epoch"]),
                       "attempt": token(context["attempt"]), "operation": context["operation"],
                       "generation": token(context["generation"]), "payloadSha256": digest(context["payloadSha256"]),
                       "stateDirectorySha256": sha256(str(directory).encode("utf-8")), "sourceSha256": source_hash}
    if binding["operation"] not in OPERATIONS or (binding["operation"] == "restore") != (source_hash is not None):
        raise invalid()
    saved = read_bytes(destination / "preservation.json")
    before = destination / "before"
    if saved is not None:
        row = object_fields(parse_bytes(saved), set(binding) | {"beforeSha256"})
        expected = digest(row["beforeSha256"])
        if {name: value for name, value in row.items() if name != "beforeSha256"} != binding:
            raise invalid()
        if os.path.lexists(before / "manifest.json"):
            result = Archive.load(before)
            if result.digest != expected:
                raise invalid()
            return result
    else:
        if any(destination.iterdir()):
            raise invalid()
        expected = None
    data = snapshot(directory, metadata_names(directory, extra))
    manifest = entry_manifest(data)
    checksum = sha256(canonical_bytes(manifest, MANIFEST_LIMIT))
    if expected is not None and checksum != expected:
        raise invalid()
    if saved is None:
        publish_bytes(destination / "preservation.json", canonical_bytes({**binding, "beforeSha256": checksum}))
    return _write_entry(before, data, manifest)
