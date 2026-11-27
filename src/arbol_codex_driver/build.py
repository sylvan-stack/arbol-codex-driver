import re
import tomllib
from pathlib import Path

from .errors import Failure
from .json_types import Object, loads


def qualified_capabilities() -> Object:
    from .admission import current_session, standalone_launch

    if not standalone_launch.get():
        current_session()
    return {"subscriptionIdentity": 1}


def build_identity(start: Path | None = None) -> Object:
    if start is None:
        from .admission import current_session

        try:
            session = current_session()
        except Failure:
            session = None
        if session is not None:
            payload = session.authority.producer
            try:
                project = tomllib.loads(payload.regular_file("pyproject.toml").read_text())["project"]
                version = project["version"]
                if project["name"] != "arbol-codex-driver" or not isinstance(version, str) or re.fullmatch(
                    r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", version,
                ) is None:
                    raise ValueError
            except (OSError, KeyError, TypeError, ValueError):
                raise Failure("internal", "Cannot read immutable Driver package version.") from None
            return {"version": version, "build": payload.declaration.build}
    directory = start or Path(__file__).resolve().parent
    while True:
        file = directory / "build.json"
        if not file.exists():
            file = directory / "package-manifest.json"
        try:
            value = loads(file.read_text())
        except FileNotFoundError:
            value = None
        except (OSError, ValueError):
            raise Failure("internal", f"Cannot read Build record {file}.") from None
        if value is not None or file.exists():
            if (
                not isinstance(value, dict)
                or value.get("component") != "arbol-codex-driver"
                or not isinstance(value.get("build"), str)
                or not re.fullmatch(r"0|[1-9a-f][0-9a-f]*", str(value["build"]))
                or not isinstance(value.get("packageVersion"), str)
                or not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][\w.-]+)?", str(value["packageVersion"]))
            ):
                raise Failure("internal", f"Invalid Build record {file}.")
            return {"version": value["packageVersion"], "build": value["build"]}
        try:
            project = tomllib.loads((directory / "pyproject.toml").read_text()).get("project", {})
        except FileNotFoundError:
            project = {}
        except (OSError, ValueError):
            raise Failure("internal", "Cannot read the Driver package version.") from None
        if project.get("name") == "arbol-codex-driver" and isinstance(project.get("version"), str):
            return {"version": project["version"], "build": "0"}
        try:
            package = loads((directory / "package.json").read_text())
        except FileNotFoundError:
            package = None
        except (OSError, ValueError):
            raise Failure("internal", "Cannot read the Driver package version.") from None
        if (
            isinstance(package, dict)
            and package.get("name") == "@sylvan-stack/arbol-codex-driver"
            and isinstance(package.get("version"), str)
        ):
            return {"version": package["version"], "build": "0"}
        if directory.parent == directory:
            raise Failure("internal", "The Driver has no package or Build record.")
        directory = directory.parent
