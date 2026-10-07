"""Classify Codex turn failures using the tool's structured error information."""

import re

from .errors import Failure, safe_text
from .json_types import Json, Object, loads, number, object_value, string

CONNECTION_CLASSES = frozenset(
    (
        "httpConnectionFailed",
        "responseStreamConnectionFailed",
        "responseStreamDisconnected",
        "responseTooManyFailedAttempts",
    )
)
RATE_PHRASES = (
    "rate limit",
    "rate_limit",
    "too many requests",
    "usage limit",
    "usage cap",
    "insufficient_quota",
    "limit reached",
    "you've hit your",
    "you have hit your",
    "weekly limit",
    "daily limit",
)
AUTH_PHRASES = ("not logged in", "logged out", "codex login", "invalid api key", "missing credentials", "please login")
NEWER_PHRASES = ("requires a newer version of codex", "requires a newer version of the codex")
WAIT = re.compile(
    r"\b(retry\s+after|retry\s+in|try\s+again\s+in|wait)\s+(\d+(?:\.\d+)?)"
    r"\s*(seconds?|secs?|s|minutes?|mins?|m)\b",
    re.I,
)
UNITLESS_WAIT = re.compile(r"\bretry\s+after\s+(\d+(?:\.\d+)?)(?![\w.])(?:\s*(?:[.,;!?]|$))", re.I)


def error_class(error: Json) -> tuple[str | None, Object]:
    info = object_value(error).get("codexErrorInfo")
    if isinstance(info, str):
        return info, {}
    if isinstance(info, dict) and len(info) == 1:
        name, value = next(iter(info.items()))
        return name, object_value(value)
    return None, {}


def vendor_answer(error: Json) -> Object:
    """A vendor JSON body is meaningful only when Codex has no specific class."""
    name, _ = error_class(error)
    if name not in ("other", None):
        return {}
    return message_answer(error) or {}


def message_answer(error: Json) -> Object | None:
    message = string(object_value(error).get("message"))
    if message is None:
        return None
    try:
        value = loads(message)
        return value if isinstance(value, dict) else None
    except (ValueError, RecursionError):
        return None


def structured_error_status(error: Json) -> int | None:
    _, info = error_class(error)
    status = info.get("httpStatusCode")
    if type(status) is int and status >= 100:
        return status
    status = vendor_answer(error).get("status")
    return status if type(status) is int and status >= 100 else None


def text_wait(message: str) -> float | None:
    match = WAIT.search(message)
    if match is not None:
        value = float(match[2])
        value *= 60 if match[3].lower().startswith("m") else 1
        if number(value):
            return value
        return None
    match = UNITLESS_WAIT.search(message)
    if match is not None:
        value = float(match[1])
        if number(value):
            return value
    return None


def unsupported_input(answer: Object) -> bool:
    if type(answer.get("status")) is not int or answer.get("status") != 400:
        return False
    error = object_value(answer.get("error"))
    message = (string(error.get("message")) or "").lower()
    code, param = string(error.get("code")), string(error.get("param"))
    if param == "reasoning.effort" and (
        code in ("unsupported_value", "invalid_enum_value")
        or "unsupported value" in message
        or "invalid value" in message
        or "not supported" in message
    ):
        return True
    return bool(
        re.search(r"\bmodel\b.*\bnot supported\b", message)
        or re.search(r"\bnot supported\b.*\bmodel\b", message)
        or param == "model"
        and code in ("model_not_found", "unsupported_model", "unsupported_value")
    )


def classify_error(error: Json, *, tool_version: str | None = None, secrets: tuple[str, ...] = ()) -> Object:
    source = object_value(error)
    name, _ = error_class(error)
    answer = vendor_answer(error)
    display_answer = message_answer(error)
    vendor = object_value((display_answer or {}).get("error"))
    message = string(vendor.get("message")) or string(source.get("message")) or "codex failed the turn."
    # Never place an entire JSON vendor response in the Leather Bag's message.
    if display_answer is not None and not string(vendor.get("message")):
        message = "The vendor refused the Codex turn."
    status = structured_error_status(error)
    wording = message.lower()
    basis = "wording" if name in ("other", None) else "fields"
    if name == "unauthorized" or status in (401, 403):
        code = "credential_rejected"
        basis = "fields"
    elif name in ("usageLimitExceeded", "rateLimitExceeded"):
        code = "rate_limited"
    elif name == "contextWindowExceeded":
        code = "context_exceeded"
    elif (
        name in ("serverOverloaded", "internalServerError", "flexUnavailable")
        or name in CONNECTION_CLASSES
        and (status is None or status >= 500)
    ):
        code = "vendor_unavailable"
    elif name in (
        "cyberPolicy",
        "misalignmentPolicyViolation",
        "tooManyDenials",
        "badRequest",
        "sessionBudgetExceeded",
    ):
        code = "vendor_error"
    elif name in ("sandboxError", "threadRollbackFailed", "activeTurnNotSteerable"):
        code = "tool_failed"
    elif name == "other" and unsupported_input(answer):
        code = "invalid_input"
        basis = "fields"
    elif name == "other" and any(phrase in wording for phrase in NEWER_PHRASES):
        code = "tool_unsupported"
        basis = "wording"
    elif name in ("other", None) and any(phrase in wording for phrase in RATE_PHRASES):
        code = "rate_limited"
        basis = "wording"
    elif name in ("other", None) and any(phrase in wording for phrase in AUTH_PHRASES):
        code = "credential_rejected"
        basis = "wording"
    else:
        code = "vendor_error"
    detail: Object = {"basis": basis}
    if status is not None:
        detail["vendorStatus"] = status
    vendor_code = string(vendor.get("code")) or name
    if vendor_code is not None:
        detail["vendorCode"] = safe_text(vendor_code, secrets, 256)
    if tool_version is not None:
        detail["toolVersion"] = safe_text(tool_version, secrets, 64)
    extra: Object = {"detail": detail}
    remedy = {
        "invalid_input": "Change the request.",
        "credential_rejected": "Sign in again, or replace the key.",
        "rate_limited": "Wait until the limit resets, or use another Subscription.",
        "context_exceeded": "Start a new chat, or continue from a shorter history.",
        "vendor_unavailable": "Try again.",
        "tool_unsupported": "Update codex.",
    }.get(code)
    if remedy is not None:
        extra["remedy"] = remedy
    if code == "rate_limited":
        wait = text_wait(message)
        if wait is not None and number(wait):
            extra["retryAfterSeconds"] = wait
    return Failure(code, message, extra, secrets).result
