from dataclasses import dataclass

from .errors import Failure

type Options = dict[str, str | bool | list[str]]


@dataclass
class Command:
    name: str
    positionals: list[str]
    options: Options
    tool_required: bool = False


@dataclass(frozen=True)
class Schema:
    minimum: int = 0
    maximum: int = 0
    values: tuple[str, ...] = ()
    flags: tuple[str, ...] = ()
    repeat: tuple[str, ...] = ()
    tool: bool = False


SCHEMAS = {
    "info": Schema(),
    "run": Schema(
        0,
        1,
        (
            "request",
            "subscription",
            "model",
            "effort",
            "service-tier",
            "system-prompt-file",
            "cwd",
            "tools",
            "chat-session",
            "run-id",
            "output",
        ),
        ("control",),
        ("add-dir", "label"),
        True,
    ),
    "runs list": Schema(),
    "runs stop": Schema(1, 1),
    "subscriptions families": Schema(),
    "subscriptions list": Schema(),
    "subscriptions create": Schema(values=("family", "label", "id")),
    "subscriptions update": Schema(1, 1, ("label",)),
    "subscriptions remove": Schema(1, 1, flags=("force",)),
    "subscriptions sign-in": Schema(1, 1, flags=("by-code",), tool=True),
    "subscriptions sign-out": Schema(1, 1, flags=("force",)),
    "subscriptions check": Schema(1, 1, tool=True),
    "subscriptions usage": Schema(1, 1),
    "subscriptions models": Schema(1, 1, tool=True),
    "subscriptions import": Schema(1, 1, ("from",)),
    "dev probe": Schema(tool=True),
    "dev live-check": Schema(tool=True),
    "dev build-check": Schema(tool=True),
}


def parse_arguments(args: list[str]) -> Command:
    options: Options = {}
    words: list[str] = []
    i = 0
    while i < len(args):
        arg = args[i]
        if arg == "--":
            words.extend(args[i:])
            break
        if arg == "--state-dir" or arg.startswith("--state-dir="):
            if arg == "--state-dir":
                i += 1
                value = args[i] if i < len(args) else ""
            else:
                value = arg[len("--state-dir=") :]
            if not value or value.startswith("--") or "state-dir" in options:
                raise Failure("invalid_input", "Give --state-dir exactly one path.")
            options["state-dir"] = value
        else:
            words.append(arg)
        i += 1
    if not words:
        raise Failure("invalid_input", "Name a command, such as info.")
    first = words.pop(0)
    name = first + " " + (words.pop(0) if words else "") if first in ("subscriptions", "runs", "dev") else first
    if name == "dev stand-in":
        if len(words) < 2 or words[1] != "--" or not words[0]:
            raise Failure("invalid_input", "Use dev stand-in <folder> -- <arguments>.")
        return Command(name, words, options)
    schema = SCHEMAS.get(name)
    if schema is None:
        raise Failure("invalid_input", "Unknown Driver command.")
    positionals: list[str] = []
    positional_only = False
    i = 0
    while i < len(words):
        arg = words[i]
        i += 1
        if arg == "--" and not positional_only:
            positional_only = True
            continue
        if not arg.startswith("-") or positional_only:
            positionals.append(arg)
            continue
        if not arg.startswith("--"):
            raise Failure(
                "invalid_input", "Unknown Driver option. Build selection belongs to the arbol-builds launcher."
            )
        key, equals, value = arg[2:].partition("=")
        if key in schema.flags:
            if equals or key in options:
                raise Failure("invalid_input", f"Option --{key} takes no value and may occur once.")
            options[key] = True
        elif key in schema.values or key in schema.repeat:
            if not equals:
                value = words[i] if i < len(words) else ""
                i += 1
            if not value or (not equals and value.startswith("--")):
                raise Failure("invalid_input", f"Option --{key} needs a value.")
            if key in schema.repeat:
                previous = options.get(key)
                options[key] = [*(previous if isinstance(previous, list) else []), value]
            else:
                if key in options:
                    raise Failure("invalid_input", f"Option --{key} may occur once.")
                options[key] = value
        else:
            raise Failure("invalid_input", "Unknown Driver option.")
    if not schema.minimum <= len(positionals) <= schema.maximum:
        raise Failure("invalid_input", f"Command {name} has the wrong number of arguments.")
    if "tools" in options and options["tools"] not in ("all", "none"):
        raise Failure("invalid_input", "Tools must be all or none.")
    if "output" in options and options["output"] not in ("events", "text"):
        raise Failure("invalid_input", "Output must be events or text.")
    return Command(name, positionals, options, schema.tool)
