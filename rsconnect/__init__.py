from importlib.metadata import PackageNotFoundError, version


def _resolve_version() -> str:
    for distribution in ("rsconnect_python", "rsconnect"):
        try:
            return version(distribution)
        except PackageNotFoundError:
            continue
    return "NOTSET"


VERSION = _resolve_version()
