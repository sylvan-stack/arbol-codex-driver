INHERITED = (
    "PATH",
    "USER",
    "LOGNAME",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "LC_MESSAGES",
    "TMPDIR",
    "TMP",
    "TEMP",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "NODE_EXTRA_CA_CERTS",
)


def clean_environment(source: dict[str, str], home: str, config_home: str | None = None) -> dict[str, str]:
    """Inherit only the allow-list; private Codex homes are explicit overrides.

    Production app-servers leave config_home unset and use the owner's HOME.
    Vendor/account and Arbol identity variables never pass through implicitly.
    """
    result = {key: source[key] for key in INHERITED if key in source}
    result["HOME"] = home
    if config_home is not None:
        result["CODEX_HOME"] = config_home
    return result
