"""Run notifications update account usage without erasing a fuller last report."""

from copy import deepcopy
from typing import cast

from .catalog import normalize_usage
from .json_types import Json, Object, now, number, object_value, string, timestamp


def merge_available(previous: Object, update: Object) -> Object:
    """Null in a sparse vendor snapshot means unavailable, not a cleared value."""
    result = deepcopy(previous)
    for key, value in update.items():
        if value is None:
            continue
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = merge_available(object_value(result[key]), value)
        else:
            result[key] = deepcopy(value)
    return result


def _windows(report: Object) -> list[Object]:
    values = report.get("windows")
    return [value for value in values if isinstance(value, dict)] if isinstance(values, list) else []


def _same_window(left: Object, right: Object) -> bool:
    if "windowMinutes" in left and "windowMinutes" in right:
        return left["windowMinutes"] == right["windowMinutes"]
    return left.get("kind") == right.get("kind")


def merge_usage_reports(current: Object, update: Object, initial: Object | None = None) -> Object:
    """Merge reported fields, retaining changes made since the run began.

    A run report contains fields borrowed from its initial cached report. When
    that baseline is supplied, those unchanged fields cannot replace fresher
    values written by another usage command while the run was active.
    """
    baseline = initial or {}

    def changed(old: Object, new: Object) -> Object:
        result: Object = {}
        for key, value in new.items():
            if value is None or old.get(key) == value:
                continue
            if isinstance(value, dict):
                fields = changed(object_value(old.get(key)), value)
                if fields:
                    result[key] = fields
            else:
                result[key] = deepcopy(value)
        return result

    result = merge_available(current, changed(baseline, {key: value for key, value in update.items() if key != "windows"}))
    current_windows = deepcopy(_windows(current))
    initial_windows = _windows(baseline)
    for window in _windows(update):
        old = next((item for item in initial_windows if _same_window(item, window)), {})
        fields = changed(old, window)
        existing = next((item for item in current_windows if _same_window(item, window)), None)
        if existing is not None:
            existing.update(merge_available(existing, fields))
        else:
            current_windows.append(deepcopy(window))
    result["windows"] = cast(list[Json], current_windows)
    return result


def _seed(report: Object) -> Object:
    extra = object_value(report.get("extra"))
    by_id = object_value(extra.get("rateLimitsByLimitId"))
    limits = object_value(by_id.get("codex", next(iter(by_id.values()), None)))
    if not limits:
        limits = {}
        for key, window in zip(("primary", "secondary"), _windows(report), strict=False):
            raw: Object = {}
            for public, vendor in (("windowMinutes", "windowDurationMins"), ("usedPercent", "usedPercent")):
                if public in window:
                    raw[vendor] = window[public]
            reset = timestamp(window.get("resetsAt"))
            if reset is not None:
                raw["resetsAt"] = reset
            limits[key] = raw
    limits = merge_available(
        limits,
        {key: extra[key] for key in ("rateLimitReachedType", "credits", "spendControlReached", "individualLimit")
         if key in extra},
    )
    if "plan" in report:
        limits["planType"] = report["plan"]
    return {
        "rateLimits": limits,
        **{key: extra[key] for key in ("ordinaryUsageAllowed", "rateLimitsByLimitId", "rateLimitResetCredits", "rateLimitUpsell")
           if key in extra},
    }


def exhausted_window_wait(value: Json, now_seconds: float) -> float | None:
    """Use only a reset and exhaustion explicitly named in this vendor answer."""
    response = object_value(value)
    by_id = object_value(response.get("rateLimitsByLimitId"))
    limits = object_value(response.get("rateLimits")) or object_value(by_id.get("codex", next(iter(by_id.values()), None)))
    waits: list[float] = []
    for key in ("primary", "secondary"):
        window = object_value(limits.get(key))
        used, reset = window.get("usedPercent"), window.get("resetsAt")
        if number(used) and cast(float, used) >= 100 and number(reset):
            waits.append(max(0, cast(float, reset) - now_seconds))
    return max(waits) if waits else None


class RunLimits:
    def __init__(self, previous: Json = None, fallback_plan: str | None = None) -> None:
        self.previous = deepcopy(object_value(previous))
        self.fallback_plan = fallback_plan or string(self.previous.get("plan"))
        self._raw = _seed(self.previous)
        self._last_read: Json = None
        self.report: Object | None = None

    def observe(self, value: Json, fetched_at: str | None = None) -> Object:
        # Validate before changing the last good snapshot. A malformed update
        # must not corrupt an earlier notification that can still be persisted.
        normalize_usage(value, self.fallback_plan, fetched_at)
        assert isinstance(value, dict)
        update = deepcopy(value)
        if not isinstance(update.get("rateLimits"), dict):
            incoming_by_id = object_value(update.get("rateLimitsByLimitId"))
            incoming_limits = incoming_by_id.get("codex", next(iter(incoming_by_id.values()), None))
            if isinstance(incoming_limits, dict):
                update["rateLimits"] = incoming_limits
        self._raw = merge_available(self._raw, update)
        # A notification normally carries only rateLimits. Keep the per-limit
        # snapshot, when present in the old report, in step with that update.
        raw_limits = object_value(self._raw.get("rateLimits"))
        by_id = object_value(self._raw.get("rateLimitsByLimitId"))
        if by_id and raw_limits:
            key = string(raw_limits.get("limitId")) or ("codex" if "codex" in by_id else next(iter(by_id)))
            by_id[key] = merge_available(object_value(by_id.get(key)), raw_limits)
        report = normalize_usage(self._raw, self.fallback_plan, fetched_at or now())
        self.report = merge_usage_reports(self.previous, report)
        return deepcopy(self.report)

    def observe_read(self, value: Json, fetched_at: str | None = None) -> Object:
        report = self.observe(value, fetched_at)
        self._last_read = deepcopy(value)
        return report

    def wait_seconds(self, now_seconds: float) -> float | None:
        return exhausted_window_wait(self._last_read, now_seconds)
