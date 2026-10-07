"""The owner's transient MCP configuration and private diagnostic values."""

import math
import tomllib
from pathlib import Path

from .errors import Failure, safe_text
from .json_types import Json, Object


def json_value(value: object) -> Json:
    """Reject TOML-only values rather than changing an owner's server table."""
    if isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return value
    if isinstance(value, list):
        return [json_value(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: json_value(item) for key, item in value.items()}
    raise ValueError


def owner_mcp_config(env: dict[str, str]) -> Object:
    """Read only the configured MCP tables; never import another owner setting."""
    path = Path(env.get("HOME") or str(Path.home())) / ".codex" / "config.toml"
    try:
        with path.open("rb") as stream:
            parsed = tomllib.load(stream)
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        raise Failure("invalid_input", "Cannot read the owner's Codex MCP configuration.") from None
    if "mcp_servers" not in parsed:
        return {}
    try:
        tables = parsed["mcp_servers"]
        if not isinstance(tables, dict):
            raise ValueError
        return {"mcp_servers": json_value(tables)}
    except ValueError:
        raise Failure("invalid_input", "The owner's Codex MCP configuration is not a valid JSON table.") from None


def diagnostic_values(config: Object) -> tuple[str, ...]:
    """Keep literal private strings for diagnostics without retaining the tables."""
    values: set[str] = set()

    def collect(value: Json) -> None:
        if isinstance(value, str) and value:
            values.add(value)
        elif isinstance(value, list):
            for item in value:
                collect(item)
        elif isinstance(value, dict):
            for item in value.values():
                collect(item)

    collect(config.get("mcp_servers"))
    return tuple(sorted(values, key=lambda value: (-len(value), value)))


def sanitize_diagnostic(value: Json, private_values: tuple[str, ...]) -> Json:
    """Scrub diagnostics only; a tool's input and output keep their vendor shape."""
    if isinstance(value, str):
        return safe_text(value, private_values, None)
    if isinstance(value, list):
        return [sanitize_diagnostic(item, private_values) for item in value]
    if isinstance(value, dict):
        return {key: sanitize_diagnostic(item, private_values) for key, item in value.items()}
    return value


class DiagnosticScrubber:
    """Keep a split private value out of the retained stderr tail."""

    def __init__(self, private_values: tuple[str, ...]) -> None:
        self.private_values = private_values
        self.pending = ""

    def feed(self, text: str, *, final: bool = False) -> str:
        text = self.pending + text
        self.pending = ""
        retained = 0
        for value in self.private_values:
            for size in range(min(len(text), len(value) - 1), retained, -1):
                if value.startswith(text[-size:]):
                    retained = size
                    break
        if retained:
            if not final:
                self.pending = text[-retained:]
            text = text[:-retained]
        return safe_text(text, self.private_values, None) + ("[redacted]" if retained and final else "")
