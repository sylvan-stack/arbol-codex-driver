"""Validated JSON and the compact ECMAScript serialization used by format 1."""

import json
import math
from datetime import UTC, datetime
from typing import cast

type Json = None | bool | int | float | str | list[Json] | dict[str, Json]
type Object = dict[str, Json]


def loads(text: str) -> Json:
    def invalid_constant(value: str) -> None:
        raise ValueError("Nonfinite JSON number")

    return cast(Json, json.loads(text, parse_constant=invalid_constant))


def object_value(value: Json) -> Object:
    return value if isinstance(value, dict) else {}


def string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def number(value: Json) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def unicode_text(text: str) -> str:
    # JS strings contain UTF-16 code units. Join pairs supplied across JSON
    # strings while preserving lone units for JSON's well-formed escaping.
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


def utf8(text: str) -> bytes:
    return (
        unicode_text(text).encode("utf-8", "replace")
        if not any(0xD800 <= ord(c) <= 0xDFFF for c in unicode_text(text))
        else "".join("\ufffd" if 0xD800 <= ord(c) <= 0xDFFF else c for c in unicode_text(text)).encode()
    )


def dumps(value: Json) -> str:
    """Match JSON.stringify, including lone/split surrogates and key ordering."""
    if isinstance(value, str):
        encoded = json.dumps(unicode_text(value), ensure_ascii=False, separators=(",", ":"))
        return "".join(f"\\u{ord(c):04x}" if 0xD800 <= ord(c) <= 0xDFFF else c for c in encoded)
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, int) and abs(value) > 9007199254740991:
            try:
                value = float(value)
            except OverflowError:
                return "null"
        if not math.isfinite(value):
            return "null"
        if value == 0:
            return "0"
        if isinstance(value, int):
            return str(value)
        raw = repr(value).lower()
        if "e" in raw:
            coefficient, exponent_text = raw.split("e")
            exponent = int(exponent_text)
            if -6 <= exponent < 21:
                from decimal import Decimal

                return (
                    format(Decimal(raw), "f").rstrip("0").rstrip(".")
                    if "." in format(Decimal(raw), "f")
                    else format(Decimal(raw), "f")
                )
            return coefficient.removesuffix(".0") + "e" + ("+" if exponent >= 0 else "-") + str(abs(exponent))
        return raw.removesuffix(".0")
    if isinstance(value, list):
        return "[" + ",".join(dumps(item) for item in value) + "]"
    numeric = sorted(
        (key for key in value if key.isascii() and key.isdigit() and str(int(key)) == key and int(key) < 4294967295),
        key=int,
    )
    keys = numeric + [key for key in value if key not in numeric]
    return "{" + ",".join(dumps(key) + ":" + dumps(value[key]) for key in keys) + "}"


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def timestamp(value: Json) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except (ValueError, OverflowError):
        return None


def iso(seconds: float) -> str:
    return datetime.fromtimestamp(seconds, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
