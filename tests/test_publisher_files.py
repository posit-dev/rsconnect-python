"""Tests for :mod:`rsconnect.publisher.files` selection."""

import io
import os

from rsconnect.publisher.files import (
    STANDARD_EXCLUSIONS,
    select_config_files,
    select_default_files,
)


def _touch(root, rel):
    path = os.path.join(root, rel.replace("/", os.sep))
    os.makedirs(os.path.dirname(path) or root, exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("x")


def _make_tree(root, rels):
    for rel in rels:
        _touch(root, rel)


def test_config_files_rooted_vs_basename(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["app.py", "sub/app.py", "notes.csv", "sub/notes.csv", "requirements.txt"])
    # "/app.py" is rooted (matches only the top-level app.py); "*.csv" matches at any depth.
    selected = select_config_files(root, ["/app.py", "*.csv", "requirements.txt"])
    assert selected == ["app.py", "notes.csv", "requirements.txt", "sub/notes.csv"]


def test_config_files_directory_include(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["app.py", "data/a.csv", "data/nested/b.csv", "other/c.txt"])
    selected = select_config_files(root, ["/app.py", "data/"])
    assert selected == ["app.py", "data/a.csv", "data/nested/b.csv"]


def test_config_files_negation_excludes(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["data/keep.csv", "data/secret.csv"])
    # Later patterns win: exclude one file that an earlier pattern included.
    selected = select_config_files(root, ["data/", "!data/secret.csv"])
    assert selected == ["data/keep.csv"]


def test_config_files_standard_exclusions_win(tmp_path):
    root = str(tmp_path)
    _make_tree(
        root,
        [
            "app.py",
            "manifest.json",
            ".git/config",
            "__pycache__/app.cpython.pyc",
            "node_modules/lib/index.js",
            "big_cache/data",
        ],
    )
    # A broad include cannot override STANDARD_EXCLUSIONS.
    selected = select_config_files(root, ["**"])
    assert "app.py" in selected
    assert "manifest.json" not in selected
    assert not any(f.startswith(".git/") for f in selected)
    assert not any(f.startswith("__pycache__/") for f in selected)
    assert not any(f.startswith("node_modules/") for f in selected)
    assert not any(f.startswith("big_cache/") for f in selected)


def test_config_files_unmatched_are_dropped(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["app.py", "extra.txt"])
    selected = select_config_files(root, ["/app.py"])
    assert selected == ["app.py"]


def test_config_files_skips_python_venv(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["app.py", "venv/bin/python", "venv/lib/site.py"])
    selected = select_config_files(root, ["**"])
    assert "app.py" in selected
    assert not any(f.startswith("venv/") for f in selected)


def test_default_files_honors_gitignore(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["app.py", "keep.txt", "build/out.o", "secret.log"])
    _touch(root, ".gitignore")
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as handle:
        handle.write("build/\n*.log\n")
    selected = select_default_files(root)
    assert "app.py" in selected
    assert "keep.txt" in selected
    assert ".gitignore" in selected
    assert not any(f.startswith("build/") for f in selected)
    assert "secret.log" not in selected


def test_default_files_nested_gitignore(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["app.py", "sub/keep.py", "sub/skip.tmp", "skip.tmp"])
    with open(os.path.join(root, "sub", ".gitignore"), "w", encoding="utf-8") as handle:
        handle.write("*.tmp\n")
    selected = select_default_files(root)
    # Nested .gitignore only affects its own subtree.
    assert "sub/keep.py" in selected
    assert "sub/skip.tmp" not in selected
    assert "skip.tmp" in selected


def test_default_files_gitignore_negation(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["a.log", "keep.log"])
    with open(os.path.join(root, ".gitignore"), "w", encoding="utf-8") as handle:
        handle.write("*.log\n!keep.log\n")
    selected = select_default_files(root)
    assert "keep.log" in selected
    assert "a.log" not in selected


def test_default_files_skips_hardcoded_dirs(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["app.py", ".git/config", "__pycache__/x.pyc", "node_modules/m/i.js"])
    selected = select_default_files(root)
    assert selected == ["app.py"]


def test_standard_exclusions_are_all_negations():
    assert all(pat.startswith("!") for pat in STANDARD_EXCLUSIONS)


# --- integration: create_file_list honors the injected restriction -----------


def test_create_file_list_restrict_applies_builder_excludes(tmp_path):
    from rsconnect.bundle import create_file_list, restrict_to_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "helpers.py", "data.csv", "requirements.txt"])
    # The builder excludes its separately-added files (env file + manifest.json).
    with restrict_to_files(["app.py", "requirements.txt"]):
        files = create_file_list(root, [], ["requirements.txt", "manifest.json"])
    # Restricted to the two, then requirements.txt dropped by the builder exclude.
    assert files == ["app.py"]


def test_create_file_list_no_restrict_walks_all(tmp_path):
    from rsconnect.bundle import create_file_list

    root = str(tmp_path)
    _make_tree(root, ["app.py", "helpers.py", "data.csv", "requirements.txt"])
    files = create_file_list(root, [], ["requirements.txt", "manifest.json"])
    assert set(files) == {"app.py", "helpers.py", "data.csv"}


def test_create_file_list_explicit_include_files_param(tmp_path):
    from rsconnect.bundle import create_file_list

    root = str(tmp_path)
    _make_tree(root, ["app.py", "helpers.py"])
    files = create_file_list(root, [], [], include_files=["app.py"])
    assert files == ["app.py"]


def test_create_file_list_restrict_skips_missing(tmp_path):
    from rsconnect.bundle import create_file_list, restrict_to_files

    root = str(tmp_path)
    _make_tree(root, ["app.py"])
    with restrict_to_files(["app.py", "gone.py"]):
        files = create_file_list(root, [], [])
    assert files == ["app.py"]


# --- integration: resolve_bundle_files picks config vs. default --------------


def test_resolve_bundle_files_uses_config_allowlist(tmp_path):
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "helpers.py", "data.csv", "requirements.txt"])
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    (publish / "app.toml").write_text(
        '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\n'
        'files = [\n    "/app.py",\n    "/requirements.txt",\n]\n',
        encoding="utf-8",
    )
    selected = resolve_bundle_files(root, entrypoint="app.py")
    assert selected == ["app.py", "requirements.txt"]


def test_resolve_bundle_files_force_includes_entrypoint(tmp_path):
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "data.csv"])
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    # A config whose files omit the entrypoint entirely.
    (publish / "app.toml").write_text(
        '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\nfiles = [\n    "/data.csv",\n]\n',
        encoding="utf-8",
    )
    selected = resolve_bundle_files(root, entrypoint="app.py")
    assert "app.py" in selected  # force-included despite not matching a pattern
    assert "data.csv" in selected


def test_resolve_bundle_files_empty_files_means_everything(tmp_path):
    """A config with no ``files`` key means "everything" (Publisher's ``["*"]``
    default), so STANDARD_EXCLUSIONS still apply but .gitignore does not."""
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "data.csv", "__pycache__/x.pyc"])
    (tmp_path / ".gitignore").write_text("data.csv\n", encoding="utf-8")
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    # no files key at all
    (publish / "app.toml").write_text(
        '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\n',
        encoding="utf-8",
    )
    selected = resolve_bundle_files(root, entrypoint="app.py")
    assert "app.py" in selected
    # the config governs, so .gitignore is not consulted
    assert "data.csv" in selected
    # but the built-in exclusions still win
    assert not any(f.startswith("__pycache__/") for f in selected)


def test_resolve_bundle_files_default_when_no_config(tmp_path):
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "secret.log"])
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    selected = resolve_bundle_files(root)
    assert "app.py" in selected
    assert ".gitignore" in selected
    assert "secret.log" not in selected


# --- end-to-end: the executor resolves + restricts around the builder --------


def test_executor_make_bundle_restricts_to_config(tmp_path):
    import io

    from rsconnect.api import RSConnectExecutor
    from rsconnect.bundle import create_file_list

    root = str(tmp_path)
    _make_tree(root, ["app.py", "helpers.py", "requirements.txt"])
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    (publish / "app.toml").write_text(
        '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\nfiles = [\n    "/app.py",\n]\n',
        encoding="utf-8",
    )

    captured = {}

    def fake_builder(*_args, **_kwargs):
        # Inside make_bundle the restriction is active, so the shared walker sees
        # only the config's allowlisted files.
        captured["files"] = create_file_list(root, [], [])
        return io.BytesIO(b"bundle")

    # make_bundle keys off the builder name to skip manifest-driven deploys.
    fake_builder.__name__ = "make_api_bundle"

    # app_id set so make_deployment_name does not contact a server for a unique name.
    ce = RSConnectExecutor(path=root, app_id="1")
    ce.make_bundle(fake_builder)

    assert captured["files"] == ["app.py"]


# --- integration_requests propagation into the manifest ----------------------

INTEGRATION_CONFIG_TOML = (
    '"$schema" = "x"\n'
    'type = "python-shiny"\n'
    'entrypoint = "app.py"\n'
    'files = [\n    "/app.py",\n]\n\n'
    "[[integration_requests]]\n"
    'name = "My Snowflake"\n'
    'type = "snowflake"\n'
    'auth_type = "Viewer"\n'
    'guid = "abc-123"\n'
)


def _write_integration_config(tmp_path):
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    (publish / "app.toml").write_text(INTEGRATION_CONFIG_TOML, encoding="utf-8")


def test_config_manifest_overlay_maps_integration_requests():
    from rsconnect.publisher import config
    from rsconnect.publisher.store import config_manifest_overlay

    cfg = config.from_dict(
        {
            "type": "python-shiny",
            "entrypoint": "app.py",
            "integration_requests": [
                {"name": "My Snowflake", "type": "snowflake", "auth_type": "Viewer", "guid": "abc-123"}
            ],
        }
    )
    overlay = config_manifest_overlay(cfg)
    assert overlay == {
        "integration_requests": [
            {"guid": "abc-123", "name": "My Snowflake", "auth_type": "Viewer", "type": "snowflake"}
        ]
    }


def test_resolve_manifest_overlay_reads_config(tmp_path):
    from rsconnect.publisher.store import resolve_manifest_overlay

    _write_integration_config(tmp_path)
    overlay = resolve_manifest_overlay(str(tmp_path), entrypoint="app.py")
    assert overlay["integration_requests"][0]["name"] == "My Snowflake"


def test_resolve_manifest_overlay_empty_without_config(tmp_path):
    from rsconnect.publisher.store import resolve_manifest_overlay

    assert resolve_manifest_overlay(str(tmp_path)) == {}


def test_manifest_overlay_injects_into_generated_manifest():
    from rsconnect.bundle import make_source_manifest, overlay_manifest
    from rsconnect.models import AppModes

    overlay = {"integration_requests": [{"guid": "abc-123", "name": "My Snowflake", "type": "snowflake"}]}
    with overlay_manifest(overlay):
        manifest = make_source_manifest(AppModes.PYTHON_SHINY, entrypoint="app.py")
    assert manifest["integration_requests"] == overlay["integration_requests"]
    # base fields are still present and not clobbered
    assert manifest["metadata"]["appmode"] == "python-shiny"


def test_manifest_overlay_absent_when_no_context():
    from rsconnect.bundle import make_source_manifest
    from rsconnect.models import AppModes

    manifest = make_source_manifest(AppModes.PYTHON_SHINY, entrypoint="app.py")
    assert "integration_requests" not in manifest


def test_executor_propagates_integration_requests_to_manifest(tmp_path):
    from rsconnect.api import RSConnectExecutor
    from rsconnect.bundle import make_source_manifest
    from rsconnect.models import AppModes

    root = str(tmp_path)
    _make_tree(root, ["app.py"])
    _write_integration_config(tmp_path)

    captured = {}

    def fake_builder(*_args, **_kwargs):
        # Built inside make_bundle, so the overlay context is active.
        captured["manifest"] = make_source_manifest(AppModes.PYTHON_SHINY, entrypoint="app.py")
        return io.BytesIO(b"bundle")

    fake_builder.__name__ = "make_api_bundle"

    ce = RSConnectExecutor(path=root, app_id="1")
    ce.make_bundle(fake_builder)

    assert captured["manifest"]["integration_requests"][0]["guid"] == "abc-123"
