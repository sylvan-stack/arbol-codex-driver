from collections.abc import Awaitable, Callable
from typing import cast

from .errors import Failure
from .json_types import Json, Object, iso, now, number, object_value, string


def malformed(name: str) -> None:
    raise Failure("tool_failed", f"codex returned a malformed {name}.")


def nonempty(value: Json) -> bool:
    return isinstance(value, str) and bool(value.strip())


def normalize_account(value: Json) -> Object | None:
    if not isinstance(value, dict) or "account" not in value:
        malformed("account response")
    assert isinstance(value, dict)
    account = value["account"]
    if account is None:
        return None
    if not isinstance(account, dict) or not nonempty(account.get("type")):
        malformed("account response")
    assert isinstance(account, dict)
    if account["type"] != "chatgpt":
        return None
    if not nonempty(account.get("email")) or not nonempty(account.get("planType")):
        malformed("ChatGPT account")
    return {"email": account["email"], "plan": account["planType"]}


def normalize_window(value: Json) -> Object | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        malformed("usage window")
    assert isinstance(value, dict)
    minutes = value.get("windowDurationMins")
    if minutes is not None and (not number(minutes) or cast(float, minutes) <= 0):
        malformed("usage window")
    duration = cast(float | None, minutes)
    label = (
        "5-hour window"
        if duration == 300
        else "Weekly window"
        if duration == 10080
        else "Usage window"
        if duration is None
        else f"{duration / 1440:g}-day window"
        if duration % 1440 == 0
        else f"{round(duration / 60, 2):g}-hour window"
    )
    window: Object = {
        "kind": "session" if duration == 300 else "weekly" if duration == 10080 else "other",
        "label": label,
    }
    if duration is not None:
        window["windowMinutes"] = duration
    percent = value.get("usedPercent")
    if percent is not None:
        if not number(percent):
            malformed("usage window")
        window.update(usedPercent=max(0, min(100, cast(float, percent))), limitReached=cast(float, percent) >= 100)
    reset = value.get("resetsAt")
    if reset is not None:
        if not number(reset):
            malformed("usage reset time")
        try:
            window["resetsAt"] = iso(cast(float, reset))
        except (OverflowError, ValueError, OSError):
            malformed("usage reset time")
    return window


def normalize_usage(value: Json, fallback_plan: str | None = None, fetched_at: str | None = None) -> Object:
    if (
        not isinstance(value, dict)
        or "rateLimits" not in value
        and not isinstance(value.get("rateLimitsByLimitId"), dict)
    ):
        malformed("usage response")
    assert isinstance(value, dict)
    by_id = object_value(value.get("rateLimitsByLimitId"))
    limits = value.get("rateLimits")
    if limits is None:
        limits = by_id.get("codex", next(iter(by_id.values()), None))
    if limits is not None and not isinstance(limits, dict):
        malformed("usage response")
    windows: list[Json] = []
    report: Object = {
        "outcome": "ok",
        "fetchedAt": fetched_at or now(),
        "windows": windows,
        "detailsUrl": "https://chatgpt.com/codex/settings/usage",
    }
    plan = string(object_value(limits).get("planType")) or fallback_plan
    if plan is not None:
        report["plan"] = plan
    if isinstance(limits, dict):
        for key in ("primary", "secondary"):
            window = normalize_window(limits.get(key))
            if window is not None:
                windows.append(window)
    extra = {
        key: value[key]
        for key in ("ordinaryUsageAllowed", "rateLimitsByLimitId", "rateLimitResetCredits", "rateLimitUpsell")
        if key in value
    }
    extra.update(
        {
            key: object_value(limits)[key]
            for key in ("rateLimitReachedType", "credits", "spendControlReached", "individualLimit")
            if key in object_value(limits)
        }
    )
    if extra:
        report["extra"] = extra
    return report


def normalize_models(value: Json, source: str = "tool", fetched_at: str | None = None) -> Object:
    if not isinstance(value, list):
        malformed("model list")
    assert isinstance(value, list)
    models: list[Json] = []
    seen: set[str] = set()
    for raw in value:
        if not isinstance(raw, dict):
            malformed("model")
        assert isinstance(raw, dict)
        if raw.get("hidden") is True:
            continue
        if not nonempty(raw.get("id")) or not nonempty(raw.get("displayName")):
            malformed("model")
        id_ = str(raw["id"])
        if id_ in seen:
            continue
        seen.add(id_)
        model: Object = {"id": id_, "label": raw["displayName"]}
        for vendor, field in (("description", "description"), ("defaultReasoningEffort", "defaultEffort")):
            if raw.get(vendor) is not None:
                if not isinstance(raw[vendor], str) or field == "defaultEffort" and not raw[vendor]:
                    malformed("model description" if field == "description" else "default model effort")
                model[field] = raw[vendor]
        for vendor, field, inner in (
            ("supportedReasoningEfforts", "efforts", "reasoningEffort"),
            ("serviceTiers", "serviceTiers", "id"),
        ):
            if vendor in raw:
                values = raw[vendor]
                if not isinstance(values, list) or any(
                    not isinstance(item, dict) or not nonempty(item.get(inner)) for item in values
                ):
                    malformed("model efforts" if field == "efforts" else "model service tiers")
                assert isinstance(values, list)
                model[field] = list(dict.fromkeys(str(object_value(item)[inner]) for item in values))
        if "isDefault" in raw:
            if not isinstance(raw["isDefault"], bool):
                malformed("default model flag")
            model["isDefault"] = raw["isDefault"]
        models.append(model)
    return {"source": source, "fetchedAt": fetched_at or now(), "models": models}


FULL_EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"]
BUILTIN = [
    ("gpt-6.1-sol", "GPT-6.1-Sol", "Latest workhorse model for coding and everyday work.", "low"),
    ("gpt-6-astra", "GPT-6-Astra", "Frontier intelligence for the most demanding work.", "medium"),
    ("gpt-6-sol", "GPT-6-Sol", "Previous generation workhorse model.", "medium"),
    ("gpt-6-luna", "GPT-6-Luna", "Fast and affordable model for easier tasks.", "medium"),
    ("gpt-5.6-sol", "GPT-5.6-Sol", "Older generation workhorse model.", "low"),
    ("gpt-5.6-terra", "GPT-5.6-Terra", "Older balanced model for straightforward work.", "medium"),
    ("gpt-5.6-luna", "GPT-5.6-Luna", "Older fast and efficient model.", "medium"),
]


def builtin_catalog(fetched_at: str | None = None) -> Object:
    return {
        "source": "builtin",
        "fetchedAt": fetched_at or now(),
        "models": [
            {
                "id": id_,
                "label": label,
                "description": description,
                "defaultEffort": effort,
                "isDefault": index == 0,
                "efforts": [*(FULL_EFFORTS[:-1] if id_.endswith("luna") else FULL_EFFORTS)],
                "serviceTiers": ["priority"],
            }
            for index, (id_, label, description, effort) in enumerate(BUILTIN)
        ],
    }


async def read_model_catalog(
    request: Callable[[str, Json], Awaitable[Json]], fetched_at: str | None = None, fallback: bool = True
) -> Object:
    try:
        raw: list[Json] = []
        seen: set[str] = set()
        cursor: str | None = None
        while True:
            page = await request(
                "model/list",
                {
                    **({"includeHidden": False} if fallback else {}),
                    **({"cursor": cursor} if cursor is not None else {}),
                },
            )
            if not isinstance(page, dict) or not isinstance(page.get("data"), list):
                malformed("model list page")
            assert isinstance(page, dict) and isinstance(page["data"], list)
            raw.extend(page["data"])
            if page.get("nextCursor") is None:
                break
            if not nonempty(page["nextCursor"]) or str(page["nextCursor"]) in seen:
                malformed("model list cursor")
            cursor = str(page["nextCursor"])
            seen.add(cursor)
        return normalize_models(raw, fetched_at=fetched_at)
    except Exception as error:
        if not fallback or isinstance(error, Failure) and error.result["code"] == "credential_rejected":
            raise
        return builtin_catalog(fetched_at)
