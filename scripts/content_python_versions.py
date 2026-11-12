import json
import subprocess

from packaging.version import Version


def content_python_versions():
    result = subprocess.run(
        ["uv", "python", "list", "--only-downloads", "--output-format", "json"],
        check=True,
        capture_output=True,
        text=True,
    )
    versions = {
        (entry["version_parts"]["major"], entry["version_parts"]["minor"])
        for entry in json.loads(result.stdout)
        if entry["implementation"] == "cpython"
        and entry["variant"] == "default"
        and not Version(entry["version"]).is_prerelease
        and (entry["version_parts"]["major"], entry["version_parts"]["minor"]) >= (3, 8)
    }
    if not versions:
        raise RuntimeError("uv did not list any supported CPython downloads")
    return ["%s.%s" % version for version in sorted(versions)]


if __name__ == "__main__":
    print("\n".join(content_python_versions()))
