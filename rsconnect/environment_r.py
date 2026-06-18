"""Detects R dependencies from a project's renv.lock file.

Given a directory that contains an renv.lock lockfile, this module parses it
into the R version and package metadata needed for the deployment manifest.
The parse is pure: it reads only renv.lock and never invokes R or inspects
locally installed R packages. This mirrors how Posit Publisher resolves R
dependencies for Python content that also uses R (e.g. rpy2 apps).
"""

from __future__ import annotations

import json
import os
from typing import Any, Optional, Sequence, cast

from .exception import RSConnectException
from .log import logger

DEFAULT_R_PACKAGE_FILE = "renv.lock"

# Repositories renv always assumes are available, keyed by the names renv writes
# into each package's "Repository" field.
_DEFAULT_REPOSITORIES = {
    "CRAN": "https://cloud.r-project.org",
    "RSPM": "https://packagemanager.posit.co/cran/latest",
}


class REnvironment:
    """R dependencies resolved from a project's renv.lock file.

    Captures the R version and the package metadata Connect needs to restore the
    R library when deploying Python content that also depends on R.
    """

    def __init__(
        self,
        r_version: str,
        packages: dict[str, dict[str, Any]],
    ):
        self.r_version = r_version
        self.packages = packages
        self.lockfile = DEFAULT_R_PACKAGE_FILE

    @classmethod
    def create(cls, directory: str) -> Optional["REnvironment"]:
        """Resolve R dependencies from an renv.lock file in a project directory.

        Returns None when there is no renv.lock to resolve, so callers can treat
        R detection as opt-in based on the presence of the lockfile. The location
        honors RENV_PATHS_LOCKFILE and otherwise defaults to <directory>/renv.lock.

        :param directory: path to the project directory that may contain renv.lock.
        """
        lockfile_path = _renv_lockfile_path(directory)
        if not os.path.exists(lockfile_path):
            return None

        with open(lockfile_path, encoding="utf-8") as f:
            try:
                parsed = json.load(f)
            except json.JSONDecodeError as err:
                raise RSConnectException(f"{lockfile_path} is not valid JSON: {err}") from err

        # A compatible lockfile is a JSON object whose "R" section lists the
        # Repositories needed to resolve every package back to a URL. renv < 1.1.0
        # omits Repositories; malformed lockfiles may be a non-object or carry
        # null/non-dict sections. Treat all of these as incompatible rather than
        # letting them surface as an AttributeError.
        incompatible_msg = (
            f"{DEFAULT_R_PACKAGE_FILE} is not compatible: missing Repositories section. "
            "Regenerate the lockfile with renv >= 1.1.0."
        )
        if not isinstance(parsed, dict):
            raise RSConnectException(incompatible_msg)
        lockfile = cast("dict[str, Any]", parsed)

        r_section = lockfile.get("R")
        if not isinstance(r_section, dict):
            raise RSConnectException(incompatible_msg)
        r_section = cast("dict[str, Any]", r_section)
        if not r_section.get("Repositories"):
            raise RSConnectException(incompatible_msg)
        if "Bioconductor" in lockfile and not isinstance(lockfile["Bioconductor"], dict):
            raise RSConnectException(incompatible_msg)

        logger.debug(f"Resolving R dependencies from {lockfile_path}")
        return cls(
            r_version=r_section.get("Version", ""),
            packages=_lockfile_to_manifest_packages(lockfile),
        )


def _renv_lockfile_path(directory: str) -> str:
    # Mimics renv's renv_paths_lockfile() in R/paths.R: RENV_PATHS_LOCKFILE
    # overrides the location and is used verbatim, except a trailing slash means
    # "a directory" so renv.lock is appended. A relative override resolves against
    # the current working directory (matching renv), not the project directory.
    # With no override we fall back to renv's default of <project>/renv.lock.
    override = os.environ.get("RENV_PATHS_LOCKFILE")
    if override:
        if override.endswith(("/", "\\")):
            override += DEFAULT_R_PACKAGE_FILE
        return override
    return os.path.join(directory, DEFAULT_R_PACKAGE_FILE)


def _lockfile_to_manifest_packages(lockfile: Any) -> dict[str, dict[str, Any]]:
    repo_name_to_url = _find_all_repositories(lockfile)
    result: dict[str, dict[str, Any]] = {}
    for pkg_name, pkg in lockfile.get("Packages", {}).items():
        source, repository = _resolve_package_source(pkg, repo_name_to_url)
        if not source:
            raise RSConnectException(
                f"Package {pkg_name} has an unresolved source; cannot generate manifest entry. "
                "Use --exclude-renv to deploy without R dependency detection."
            )
        if not repository:
            raise RSConnectException(
                f"Package {pkg_name} has an unresolved repository; cannot generate manifest entry. "
                "Use --exclude-renv to deploy without R dependency detection."
            )
        description = _build_description(
            pkg,
            repository,
            {
                "Package": pkg_name,
                "Version": pkg.get("Version", ""),
                "Type": "Package",
                "Title": pkg.get("Title") or f"{source} R package",
            },
        )
        result[pkg_name] = {"Source": source, "Repository": repository, "description": description}
    return result


def _find_all_repositories(lockfile: Any) -> dict[str, str]:
    repos = dict(_DEFAULT_REPOSITORIES)

    bioc_version = lockfile.get("Bioconductor", {}).get("Version")
    if bioc_version:
        base = f"https://bioconductor.org/packages/{bioc_version}"
        repos["BioCsoft"] = f"{base}/bioc"
        repos["BioCann"] = f"{base}/data/annotation"
        repos["BioCexp"] = f"{base}/data/experiment"
        repos["BioCworkflows"] = f"{base}/workflows"
        repos["BioCbooks"] = f"{base}/books"

    for repo in lockfile.get("R", {}).get("Repositories", []):
        repos[repo["Name"]] = repo["URL"].rstrip("/")

    # Packages installed from a remote repository (e.g. a private RSPM) carry the
    # repository URL on the package itself; register it under its short name.
    for pkg in lockfile.get("Packages", {}).values():
        remote_repos = pkg.get("RemoteRepos")
        repository = pkg.get("Repository")
        if remote_repos and repository and _is_url(remote_repos):
            repos[repository] = remote_repos.rstrip("/")

    return repos


def _resolve_package_source(pkg: Any, repo_name_to_url: dict[str, str]) -> tuple[str, str]:
    repo_identifier = pkg.get("RemoteRepos") or pkg.get("Repository") or ""
    pkg_ref = _remote_pkg_ref_or_derived(pkg)
    remote_type = pkg.get("RemoteType")

    if not repo_identifier and remote_type:
        # git-hosted package with no standard repository
        return remote_type, (_remote_repo_url(remote_type, pkg_ref) or pkg.get("RemoteUrl") or "")

    if repo_identifier or pkg.get("Source") == "Bioconductor":
        return _resolve_repo_and_source(repo_name_to_url, repo_identifier, pkg.get("Source"))

    # No resolution possible here; the caller validates the source/repository are non-empty.
    return pkg.get("Source") or "", pkg.get("Repository") or ""


def _resolve_repo_and_source(repo_name_to_url: dict[str, str], repo_str: str, src: Optional[str]) -> tuple[str, str]:
    if _is_url(repo_str):
        repo_url = repo_str.rstrip("/")
        repo_name = repo_url
        for name, url in repo_name_to_url.items():
            if url == repo_url:
                repo_name = name
                break
    elif repo_str:
        url = repo_name_to_url.get(repo_str)
        if url is None:
            raise RSConnectException(f"repository {repo_str} cannot be resolved to a URL")
        repo_url = url
        repo_name = repo_str
    else:
        # Caller guarantees src == "Bioconductor" once repo_str is empty.
        bioc_url = repo_name_to_url.get("BioCsoft")
        if bioc_url is None:
            raise RSConnectException(
                "Bioconductor package source specified but no Bioconductor repositories are available"
            )
        repo_url = bioc_url
        repo_name = "BioCsoft"

    is_bioc = src == "Bioconductor" or repo_name.startswith("BioC") or "bioconductor.org/packages/" in repo_url.lower()
    source = "Bioconductor" if is_bioc else repo_name
    return source, repo_url


def _build_description(pkg: Any, resolved_repo: str, initial: dict[str, Any]) -> dict[str, Any]:
    # The manifest "description" mirrors the package DESCRIPTION. Connect treats it
    # as a plain JSON object, so key order is just deterministic insertion order,
    # not a contract. Writes are first-write-wins: setIf only fills a key the first
    # time a truthy value is seen, so derived values never overwrite explicit ones.
    desc = dict(initial)

    def set_if(key: str, value: Any) -> None:
        # setdefault keeps first-write-wins; the truthy guard avoids writing null/empty fields.
        if value:
            desc.setdefault(key, value)

    for key in (
        "Hash",
        "Authors@R",
        "Description",
        "License",
        "Maintainer",
        "VignetteBuilder",
        "RoxygenNote",
        "Encoding",
        "NeedsCompilation",
        "Author",
        "SystemRequirements",
        "RemoteType",
        "RemoteRef",
        "RemoteRepos",
        "RemoteReposName",
        "RemotePkgPlatform",
        "RemoteSha",
        "RemoteHost",
        "RemoteRepo",
        "RemoteUsername",
        "RemoteSubdir",
    ):
        set_if(key, pkg.get(key))
    set_if("GithubSubdir", pkg.get("RemoteSubdir"))
    set_if("RemoteUrl", pkg.get("RemoteUrl"))

    pkg_ref = _remote_pkg_ref_or_derived(pkg)
    if pkg_ref:
        desc["RemotePkgRef"] = pkg_ref

    if pkg.get("RemoteType") == "github" and pkg.get("RemotePkgRef"):
        set_if("URL", f"https://github.com/{pkg['RemotePkgRef']}")
        set_if("BugReports", f"https://github.com/{pkg['RemotePkgRef']}/issues")

    set_if("URL", pkg.get("URL"))
    set_if("BugReports", pkg.get("BugReports"))
    set_if("Repository", resolved_repo)
    set_if("Config/testthat/edition", pkg.get("Config/testthat/edition"))
    set_if("Config/Needs/website", pkg.get("Config/Needs/website"))
    set_if("Imports", _join_list(pkg.get("Imports")))
    set_if("Suggests", _join_list(pkg.get("Suggests")))
    set_if("LinkingTo", _join_list(pkg.get("LinkingTo")))

    if pkg.get("Depends"):
        set_if("Depends", _join_list(pkg.get("Depends")))
    elif pkg.get("Requirements"):
        set_if("Depends", _join_list(pkg.get("Requirements")))

    return desc


def _remote_pkg_ref_or_derived(pkg: Any) -> str:
    if pkg.get("RemotePkgRef"):
        return pkg["RemotePkgRef"]
    if pkg.get("RemoteUsername") and pkg.get("RemoteRepo"):
        return f"{pkg['RemoteUsername']}/{pkg['RemoteRepo']}"
    return ""


def _remote_repo_url(remote_type: str, pkg_ref: str) -> str:
    if not pkg_ref:
        return ""
    hosts = {
        "github": "https://github.com/",
        "gitlab": "https://gitlab.com/",
        "bitbucket": "https://bitbucket.org/",
    }
    host = hosts.get(remote_type)
    return f"{host}{pkg_ref}" if host else ""


def _join_list(value: Optional[Sequence[str]]) -> Optional[str]:
    return ", ".join(value) if value else None


def _is_url(value: str) -> bool:
    return value.startswith(("http://", "https://", "ftp://"))
