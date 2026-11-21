from pathlib import Path

from .errors import Failure
from .json_types import Object, loads
from .paths import installation_root


def settings_path(home: str) -> Path:
    return installation_root(home) / "arbol-codex-driver.json"


def read_settings(file: Path) -> tuple[Object, list[Object]]:
    try:
        text = file.read_text()
    except FileNotFoundError:
        return {}, []
    except OSError:
        raise Failure("invalid_input", f"Cannot read settings file {file}.") from None
    try:
        value = loads(text)
    except ValueError:
        raise Failure("invalid_input", f"Settings file {file} is not valid JSON.") from None
    notices: list[Object] = []

    def bad(field: str) -> None:
        raise Failure("invalid_input", f"Settings file {file}: invalid field {field}.")

    def unknown(item: Object, known: tuple[str, ...], prefix: str = "") -> None:
        for key in item:
            if key not in known:
                raise Failure("invalid_input", f"Settings file {file}: unknown field {prefix}{key}.")

    def strings(item: Object, known: tuple[str, ...], prefix: str = "") -> Object:
        clean: Object = {}
        for key in known:
            if key in item:
                if not isinstance(item[key], str) or not item[key]:
                    bad(prefix + key)
                clean[key] = item[key]
        return clean

    if not isinstance(value, dict):
        bad("(root)")
    assert isinstance(value, dict)
    unknown(value, ("toolPath", "defaultSubscription", "subscriptions"))
    result = strings(value, ("toolPath", "defaultSubscription"))
    if "subscriptions" in value:
        subscriptions = value["subscriptions"]
        if not isinstance(subscriptions, dict):
            bad("subscriptions")
        assert isinstance(subscriptions, dict)
        cleaned: Object = {}
        result["subscriptions"] = cleaned
        for id_, item in subscriptions.items():
            prefix = f"subscriptions.{id_}."
            if not isinstance(item, dict):
                bad(f"subscriptions.{id_}")
            assert isinstance(item, dict)
            unknown(item, ("defaultModel", "defaultEffort", "settings", "secret"), prefix)
            clean = strings(item, ("defaultModel", "defaultEffort"), prefix)
            if "settings" in item:
                if not isinstance(item["settings"], dict):
                    bad(prefix + "settings")
                clean["settings"] = item["settings"]
            if "secret" in item:
                raise Failure("invalid_input", f"Settings file {file}: {prefix}secret is obsolete.",
                              {"remedy": "Remove the secret setting and sign in directly in Codex."})
            cleaned[id_] = clean
    return result, notices
