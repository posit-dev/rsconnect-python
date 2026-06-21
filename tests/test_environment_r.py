import json
from os.path import join

import pytest

from rsconnect.environment_r import REnvironment
from rsconnect.exception import RSConnectException


def write_lockfile(directory, lockfile):
    with open(join(str(directory), "renv.lock"), "w", encoding="utf-8") as f:
        json.dump(lockfile, f)


def test_create_returns_none_without_lockfile(tmp_path):
    assert REnvironment.create(str(tmp_path)) is None


def test_resolves_cran_and_rspm_packages(tmp_path):
    write_lockfile(
        tmp_path,
        {
            "R": {
                "Version": "4.3.1",
                "Repositories": [
                    {"Name": "CRAN", "URL": "https://cloud.r-project.org"},
                    {"Name": "RSPM", "URL": "https://packagemanager.posit.co/cran/latest/"},
                ],
            },
            "Packages": {
                "R6": {
                    "Package": "R6",
                    "Version": "2.5.1",
                    "Source": "Repository",
                    "Repository": "CRAN",
                    "Hash": "470851b6d5d0ac559e9d01bb352b4021",
                    "Requirements": ["R"],
                },
                "glue": {
                    "Package": "glue",
                    "Version": "1.6.2",
                    "Source": "Repository",
                    "Repository": "RSPM",
                    "Title": "Interpreted String Literals",
                },
            },
        },
    )

    env = REnvironment.create(str(tmp_path))
    assert env is not None
    assert env.r_version == "4.3.1"
    assert env.lockfile == "renv.lock"

    r6 = env.packages["R6"]
    assert r6["Source"] == "CRAN"
    assert r6["Repository"] == "https://cloud.r-project.org"
    # Connect treats description as a JSON object, so assert key presence and
    # values rather than a specific key order.
    description = r6["description"]
    assert {"Package", "Version", "Type", "Title", "Hash", "Repository", "Depends"} <= description.keys()
    assert description["Package"] == "R6"
    assert description["Version"] == "2.5.1"
    assert description["Type"] == "Package"
    assert description["Hash"] == "470851b6d5d0ac559e9d01bb352b4021"
    assert description["Repository"] == "https://cloud.r-project.org"
    assert description["Title"] == "CRAN R package"
    assert description["Depends"] == "R"

    glue = env.packages["glue"]
    assert glue["Source"] == "RSPM"
    # Trailing slash on the configured repository URL is stripped.
    assert glue["Repository"] == "https://packagemanager.posit.co/cran/latest"
    assert glue["description"]["Title"] == "Interpreted String Literals"


def test_resolves_bioconductor_package(tmp_path):
    write_lockfile(
        tmp_path,
        {
            "R": {"Version": "4.3.1", "Repositories": [{"Name": "CRAN", "URL": "https://cloud.r-project.org"}]},
            "Bioconductor": {"Version": "3.18"},
            "Packages": {
                "Biobase": {"Package": "Biobase", "Version": "2.62.0", "Source": "Bioconductor"},
            },
        },
    )

    env = REnvironment.create(str(tmp_path))
    assert env is not None
    biobase = env.packages["Biobase"]
    assert biobase["Source"] == "Bioconductor"
    assert biobase["Repository"] == "https://bioconductor.org/packages/3.18/bioc"


def test_resolves_github_remote_package(tmp_path):
    write_lockfile(
        tmp_path,
        {
            "R": {"Version": "4.3.1", "Repositories": [{"Name": "CRAN", "URL": "https://cloud.r-project.org"}]},
            "Packages": {
                "shiny": {
                    "Package": "shiny",
                    "Version": "1.8.0",
                    "Source": "GitHub",
                    "RemoteType": "github",
                    "RemoteUsername": "rstudio",
                    "RemoteRepo": "shiny",
                    "RemotePkgRef": "rstudio/shiny",
                    "RemoteSha": "abc123",
                },
            },
        },
    )

    env = REnvironment.create(str(tmp_path))
    assert env is not None
    shiny = env.packages["shiny"]
    assert shiny["Source"] == "github"
    assert shiny["Repository"] == "https://github.com/rstudio/shiny"
    description = shiny["description"]
    assert description["RemoteType"] == "github"
    assert description["RemotePkgRef"] == "rstudio/shiny"
    assert description["URL"] == "https://github.com/rstudio/shiny"
    assert description["BugReports"] == "https://github.com/rstudio/shiny/issues"


def test_incompatible_lockfile_raises(tmp_path):
    write_lockfile(
        tmp_path,
        {
            "R": {"Version": "4.3.1"},
            "Packages": {"R6": {"Package": "R6", "Version": "2.5.1", "Source": "Repository", "Repository": "CRAN"}},
        },
    )

    with pytest.raises(RSConnectException, match="renv >= 1.1.0"):
        REnvironment.create(str(tmp_path))


def test_resolves_private_repo_from_remote_repos(tmp_path):
    write_lockfile(
        tmp_path,
        {
            "R": {"Version": "4.3.1", "Repositories": [{"Name": "CRAN", "URL": "https://cloud.r-project.org"}]},
            "Packages": {
                "mystery": {
                    "Package": "mystery",
                    "Version": "1.0.0",
                    "Source": "Repository",
                    "Repository": "PRIVATE",
                    "RemoteRepos": "https://my.rspm/cran/latest",
                },
            },
        },
    )

    env = REnvironment.create(str(tmp_path))
    assert env is not None
    mystery = env.packages["mystery"]
    # The short name resolves because the package carries a RemoteRepos URL.
    assert mystery["Source"] == "PRIVATE"
    assert mystery["Repository"] == "https://my.rspm/cran/latest"


def test_unresolvable_repository_raises(tmp_path):
    write_lockfile(
        tmp_path,
        {
            "R": {"Version": "4.3.1", "Repositories": [{"Name": "CRAN", "URL": "https://cloud.r-project.org"}]},
            "Packages": {
                "mystery": {
                    "Package": "mystery",
                    "Version": "1.0.0",
                    "Source": "Repository",
                    "Repository": "PRIVATE",
                },
            },
        },
    )

    with pytest.raises(RSConnectException, match="PRIVATE cannot be resolved"):
        REnvironment.create(str(tmp_path))


def test_malformed_lockfile_raises(tmp_path):
    # A valid-JSON but non-object lockfile must fail cleanly, not with an AttributeError.
    with open(join(str(tmp_path), "renv.lock"), "w", encoding="utf-8") as f:
        f.write("[]")
    with pytest.raises(RSConnectException, match="not compatible"):
        REnvironment.create(str(tmp_path))


def test_null_r_section_raises(tmp_path):
    write_lockfile(tmp_path, {"R": None, "Packages": {}})
    with pytest.raises(RSConnectException, match="renv >= 1.1.0"):
        REnvironment.create(str(tmp_path))


MINIMAL_LOCKFILE = {
    "R": {"Version": "4.3.1", "Repositories": [{"Name": "CRAN", "URL": "https://cloud.r-project.org"}]},
    "Packages": {},
}


def test_renv_paths_lockfile_absolute_override(tmp_path, monkeypatch):
    # RENV_PATHS_LOCKFILE points at a lockfile outside the project directory, using
    # a non-default filename to prove the override is used verbatim.
    lockfile = tmp_path / "elsewhere" / "custom.lock"
    lockfile.parent.mkdir()
    lockfile.write_text(json.dumps(MINIMAL_LOCKFILE), encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("RENV_PATHS_LOCKFILE", str(lockfile))

    env = REnvironment.create(str(project))
    assert env is not None
    assert env.r_version == "4.3.1"


def test_renv_paths_lockfile_trailing_slash_appends_renv_lock(tmp_path, monkeypatch):
    # A trailing slash means "a directory"; renv.lock is appended to it.
    lockdir = tmp_path / "locks"
    lockdir.mkdir()
    (lockdir / "renv.lock").write_text(json.dumps(MINIMAL_LOCKFILE), encoding="utf-8")
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.setenv("RENV_PATHS_LOCKFILE", str(lockdir) + "/")

    env = REnvironment.create(str(project))
    assert env is not None
    assert env.r_version == "4.3.1"


def test_renv_paths_lockfile_relative_override_resolves_against_project(tmp_path, monkeypatch):
    # A relative RENV_PATHS_LOCKFILE resolves against the project directory, not the
    # current working directory (matching renv).
    project = tmp_path / "project"
    (project / "config").mkdir(parents=True)
    (project / "config" / "custom.lock").write_text(json.dumps(MINIMAL_LOCKFILE), encoding="utf-8")
    # Run from a different directory to prove resolution ignores the CWD.
    workdir = tmp_path / "workdir"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("RENV_PATHS_LOCKFILE", join("config", "custom.lock"))

    env = REnvironment.create(str(project))
    assert env is not None
    assert env.r_version == "4.3.1"
