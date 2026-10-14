from pathlib import Path

from .errors import Failure
from .json_types import Object, loads


def settings_path(home: str) -> Path:
    return Path(home) / ".arbol" / "arbol-codex-driver.json"


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
                secret = item["secret"]
                if not isinstance(secret, dict):
                    bad(prefix + "secret")
                assert isinstance(secret, dict)
                if secret.get("from") == "keychain":
                    unknown(secret, ("from",), prefix + "secret.")
                    clean["secret"] = {"from": "keychain"}
                elif secret.get("from") == "command":
                    unknown(secret, ("from", "command"), prefix + "secret.")
                    command = secret.get("command")
                    if (
                        not isinstance(command, list)
                        or not command
                        or not command[0]
                        or not all(isinstance(arg, str) for arg in command)
                    ):
                        bad(prefix + "secret.command")
                    clean["secret"] = {"from": "command", "command": command}
                else:
                    bad(prefix + "secret.from")
            cleaned[id_] = clean
    return result, notices
