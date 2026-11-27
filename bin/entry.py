"""Isolated trusted entry; no application import precedes path confinement."""

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


def bootstrap() -> None:
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
    if not any(name in os.environ for name in (
        "ARBOL_DRIVER_ADMISSION_FD", "ARBOL_DRIVER_ADMISSION_CONTEXT",
        "ARBOL_DRIVER_MAINTENANCE_FD", "ARBOL_DRIVER_MAINTENANCE_CONTEXT",
    )):
        sys.path.insert(0, os.path.join(root, "src"))
        from arbol_codex_driver.cli import entry

        entry()
        return
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
    from arbol_codex_driver.payload import bootstrap_entry

    bootstrap_entry(root, script, bytes(raw))


try:
    bootstrap()
except SystemExit:
    raise
except BaseException:
    refuse()
