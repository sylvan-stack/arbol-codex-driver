"""Package original standalone CPython bytes and this Driver into its final folder."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_support import (  # noqa: E402
    COMPONENT,
    ENTRY,
    IDENTITY_METADATA,
    PAYLOAD,
    ROOT,
    build_folder,
    committed_snapshot,
    digest,
    metadata,
    source_provenance,
    target,
)
from identity_package import emit, inventory, validate_links  # noqa: E402


def archive(distribution: dict[str, Any]) -> Path:
    checksum = distribution.get("sha256")
    url = distribution.get("url")
    if (not isinstance(checksum, str) or re.fullmatch(r"[0-9a-f]{64}", checksum) is None or not isinstance(url, str)
            or not url.startswith("https://github.com/astral-sh/python-build-standalone/releases/download/")):
        raise ValueError("The standalone distribution must have a pinned URL and SHA-256 digest.")
    cache = Path(os.environ.get("ARBOL_PYTHON_ARCHIVE_CACHE", str(Path.home() / ".cache/arbol-driver-build/python")))
    cache.mkdir(parents=True, exist_ok=True)
    destination = cache / f"{checksum}.tar.gz"
    if destination.exists() and digest(destination) != checksum:
        raise ValueError("The cached standalone Python archive has the wrong SHA-256 digest.")
    if not destination.exists():
        fd, name = tempfile.mkstemp(prefix="download-", suffix=".tar.gz", dir=cache)
        os.close(fd)
        temporary = Path(name)
        try:
            with urllib.request.urlopen(url, timeout=60) as response, temporary.open("wb") as output:
                shutil.copyfileobj(response, output)
            if digest(temporary) != checksum:
                raise ValueError("The downloaded standalone Python archive has the wrong SHA-256 digest.")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
    return destination


def package(candidate: str | None) -> Path:
    folder, number = build_folder(candidate)
    if folder == ROOT or folder in ROOT.parents or ROOT in folder.parents:
        raise ValueError("The Build folder must not overlap its source checkout.")
    compatibility = ("runtime", "src", "tests", "scripts", "bin", "package.json", "pyproject.toml",
                     ".python-version", "uv.lock", "README.md", "package-manifest.json")
    payload = folder / PAYLOAD
    if os.path.lexists(payload) or any(os.path.lexists(folder / name) for name in compatibility):
        raise ValueError("Refusing to overwrite an existing packaged program.")
    source = source_provenance()
    with committed_snapshot(ROOT, source) as committed:
        version, pin = metadata(committed)
        selected = target()
        distribution = pin["distributions"][selected]
        compressed = archive(distribution)
        payload.mkdir(mode=0o700)
        runtime = payload / "runtime"
        runtime.mkdir(mode=0o700)
        # Original relocatable install_only bytes, never a host/venv link.
        with tarfile.open(compressed, "r:gz") as bundle:
            bundle.extractall(runtime, filter="data")
        interpreter = runtime / "python/bin/python3.14"
        probe = subprocess.run([str(interpreter), "-ISB", "-c", "import platform; print(platform.python_version())"],
                               check=True, capture_output=True, text=True, cwd=payload)
        if probe.stdout.strip() != pin["version"]:
            raise ValueError("The extracted interpreter does not match the pinned Python version.")
        package_name = COMPONENT.replace("-", "_")
        (payload / "src").mkdir()
        shutil.copytree(committed / "src" / package_name, payload / "src" / package_name, symlinks=True)
        shutil.copytree(committed / "tests", payload / "tests", symlinks=True)
        for name in ("package.json", "pyproject.toml", ".python-version", "uv.lock", "README.md"):
            shutil.copy2(committed / name, payload / name, follow_symlinks=False)
        scripts = payload / "scripts"
        scripts.mkdir()
        for item in (committed / "scripts").iterdir():
            if item.suffix in (".py", ".json"):
                shutil.copy2(item, scripts / item.name, follow_symlinks=False)
        binary = payload / "bin"
        binary.mkdir()
        shutil.copy2(committed / "bin/entry.py", binary / "entry.py", follow_symlinks=False)
        executable = payload / ENTRY
        executable.write_text(
            '#!/bin/sh\ndirectory=${0%/*}\n[ "$directory" != "$0" ] || directory=.\n'
            'directory=$(CDPATH= cd -P -- "$directory" && pwd -P) || exit 1\n'
            'root=$(CDPATH= cd -P -- "$directory/.." && pwd -P) || exit 1\n'
            'exec "$root/runtime/python/bin/python3.14" -ISB "$root/bin/entry.py" "$@"\n', encoding="utf-8")
        executable.chmod(0o755)
        # Reject external/cyclic links before even historical provenance hashing.
        validate_links(inventory(payload))
        manifest = {
            "format": 1, "component": COMPONENT, "packageVersion": version, "entry": ENTRY,
            "build": number or "0", "candidate": number is None, "source": source,
            "python": {"version": pin["version"], "target": selected, "provider": pin["provider"],
                       "release": pin["release"], "archiveUrl": distribution["url"],
                       "archiveSha256": distribution["sha256"], "executable": "runtime/python/bin/python3.14",
                       "executableSha256": digest(interpreter)},
            "files": {path.relative_to(payload).as_posix(): digest(path) for path in sorted(payload.rglob("*"))
                      if path.is_file() and runtime not in path.parents
                      and path.relative_to(payload).as_posix() not in IDENTITY_METADATA | {"package-manifest.json"}},
        }
        (payload / "package-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        if source_provenance() != source:
            raise ValueError("Source changed during committed packaging.")
        if number is not None:
            emit(payload, number, source)
        # Unregistered candidates retain provenance but get no D/acceptance.
        # Existing gates keep their exact root paths into these same bytes.
        for name in compatibility:
            (folder / name).symlink_to(Path(PAYLOAD) / name, target_is_directory=(payload / name).is_dir())
    return folder


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", help="Absolute empty folder for a development candidate, outside the numbered registry")
    arguments = parser.parse_args()
    try:
        folder = package(arguments.candidate)
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(f"Cannot package {COMPONENT}: {error}", file=sys.stderr)
        return 1
    print(f"Packaged {COMPONENT} in {folder}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
