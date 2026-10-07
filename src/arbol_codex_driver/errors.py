from .json_types import Json, Object, object_value, utf8

ERROR_CODES = (
    "invalid_input",
    "not_found",
    "in_use",
    "unsupported",
    "not_signed_in",
    "credential_rejected",
    "rate_limited",
    "context_exceeded",
    "vendor_unavailable",
    "vendor_error",
    "tool_missing",
    "tool_unsupported",
    "tool_failed",
    "limit_reached",
    "state_newer",
    "internal",
)


def safe_text(text: str, secrets: tuple[str, ...] = (), limit: int | None = 1024) -> str:
    for secret in sorted(secrets, key=len, reverse=True):
        if secret:
            text = text.replace(secret, "[redacted]")
    raw = utf8(text)
    return raw[-limit:].decode("utf-8", "ignore") if limit is not None and len(raw) > limit else text


def redact(value: Json, secrets: tuple[str, ...]) -> Json:
    if isinstance(value, str):
        return safe_text(value, secrets, None)
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {safe_text(key, secrets, None): redact(item, secrets) for key, item in value.items()}
    return value


class Failure(Exception):
    result: Object

    def __init__(self, code: str, message: str, extra: Object | None = None, secrets: tuple[str, ...] = ()) -> None:
        if code not in ERROR_CODES:
            raise ValueError("Unknown Driver error code")
        super().__init__(safe_text(message, secrets))
        self.result = {
            **object_value(redact(extra or {}, secrets)),
            "code": code,
            "message": str(self),
            "retryable": code in ("rate_limited", "vendor_unavailable"),
        }
        detail = self.result.get("detail")
        if isinstance(detail, dict) and isinstance(detail.get("excerpt"), str):
            detail["excerpt"] = safe_text(str(detail["excerpt"]), secrets)
        if code != "rate_limited":
            self.result.pop("retryAfterSeconds", None)


def safe_failure(error: BaseException) -> Object:
    return (
        error.result
        if isinstance(error, Failure)
        else Failure("internal", "The Driver could not complete this operation.").result
    )
