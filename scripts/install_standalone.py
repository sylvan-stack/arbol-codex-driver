"""Install a numbered Codex Driver package and select its existing state directory."""

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import stat
import tempfile
from pathlib import Path

COMMAND = "arbol-codex-driver"


def install(candidate: Path, state: Path) -> str:
    payload = candidate.resolve(strict=True) / "driver-payload"
    manifest = json.loads((payload / "package-manifest.json").read_text())
    build = manifest["build"]
    if (
        manifest["component"] != COMMAND or not isinstance(build, str)
        or not re.fullmatch(r"[1-9a-f][0-9a-f]*", build)
        or manifest["source"]["uncommittedChanges"] is not False
    ):
        raise ValueError("Select a numbered Codex Driver package built from committed source.")
    state = state.resolve(strict=True)
    if (state / "format").read_text() != "2\n":
        raise ValueError("Select the existing Codex Driver format-2 directory.")
    if state.stat().st_uid != os.getuid() or stat.S_IMODE(state.stat().st_mode) != 0o700:
        raise ValueError("The Codex Driver state directory must be private.")

    home = Path.home()
    route = home / "Applications" / "Arbol Codex Driver" / "bin" / COMMAND
    previous = home / "Applications" / "Arbol" / "bin" / COMMAND
    alias = home / ".local" / "bin" / COMMAND
    if os.path.lexists(alias) and (
        not alias.is_symlink() or Path(os.readlink(alias)) not in (route, previous)
    ):
        raise ValueError("The public Codex Driver command belongs to another installation.")
    library = home / ".local" / "lib" / "sylvan-stack" / COMMAND
    library.mkdir(mode=0o700, parents=True, exist_ok=True)
    route.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    alias.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    destination = library / build
    state_guard = os.open(state / "identity.guard", os.O_RDWR | os.O_NOFOLLOW)
    try:
        fcntl.flock(state_guard, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if destination.exists():
            raise ValueError(f"Codex Driver Build {build} already exists in the standalone installation.")
        with tempfile.TemporaryDirectory(dir=library) as staging:
            prepared = Path(staging) / build
            prepared.mkdir(mode=0o700)
            shutil.copytree(payload, prepared / "driver-payload", symlinks=True)
            os.rename(prepared, destination)
        executable = destination / "driver-payload" / "bin" / COMMAND
        with tempfile.TemporaryDirectory(dir=route.parent) as staging:
            prepared = Path(staging) / COMMAND
            prepared.write_text(
                "#!/bin/sh\n"
                "unset ARBOL_DRIVER_ADMISSION_FD ARBOL_DRIVER_ADMISSION_CONTEXT "
                "ARBOL_DRIVER_MAINTENANCE_FD ARBOL_DRIVER_MAINTENANCE_CONTEXT\n"
                f'exec {shlex.quote(str(executable))} --state-dir {shlex.quote(str(state))} "$@"\n'
            )
            prepared.chmod(0o755)
            os.replace(prepared, route)
        with tempfile.TemporaryDirectory(dir=alias.parent) as staging:
            prepared = Path(staging) / COMMAND
            prepared.symlink_to(route)
            os.replace(prepared, alias)
    finally:
        os.close(state_guard)
    return build


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    print(f"Installed standalone Codex Driver Build {install(args.candidate, args.state_dir)}.")
