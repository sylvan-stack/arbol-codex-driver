"""Installed Codex Driver paths (ARC-5)."""

from pathlib import Path


def installation_root(home: Path | str) -> Path:
    return Path(home) / ".arbol"
