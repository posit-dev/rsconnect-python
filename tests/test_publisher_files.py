"""Tests for :mod:`rsconnect.publisher.files` selection."""

import io
import os

from rsconnect.publisher.files import (
    STANDARD_EXCLUSIONS,
    select_config_files,
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


def test_resolve_bundle_files_none_for_unrestricted_config(tmp_path):
    """A config that declares no real restriction imposes none.

    An absent ``files``, an explicit ``["*"]``, ``["*"]`` plus the ``.posit`` paths
    rsconnect writes, and ``["*"]`` plus a literal package-file entry (the form
    rsconnect now writes for Python content, so Publisher's redeploy preflight --
    which checks ``files`` by literal suffix instead of expanding globs -- can find
    ``requirements.txt``) all mean "everything", so bundling must fall through to
    the caller's unchanged whole-tree walk rather than a re-derived allowlist."""
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "data.csv"])
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    header = '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\n'
    for files_line in (
        "",  # no files key at all
        'files = ["*"]\n',
        'files = ["*", "/.posit/publish/app.toml"]\n',
        'files = ["*", "/requirements.txt"]\n',
    ):
        (publish / "app.toml").write_text(header + files_line, encoding="utf-8")
        assert resolve_bundle_files(root, entrypoint="app.py") is None, files_line


def test_resolve_bundle_files_restricts_for_a_curated_config(tmp_path):
    """A config listing real content patterns *is* honored -- that is the feature."""
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "data.csv", "__pycache__/x.pyc"])
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    (publish / "app.toml").write_text(
        '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\nfiles = ["/app.py"]\n',
        encoding="utf-8",
    )
    selected = resolve_bundle_files(root, entrypoint="app.py")
    assert selected == ["app.py"]


def test_resolve_bundle_files_honors_curation_alongside_posit_paths(tmp_path):
    """Publisher writes the curated content patterns *and* the ``.posit`` paths.

    The ``.posit`` entries must not make the list look unrestricted -- the whole
    point of curating in Publisher is that the listed files are the ones that
    ship."""
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "helpers.py", "secrets.txt", "junk.csv"])
    publish = tmp_path / ".posit" / "publish"
    (publish / "deployments").mkdir(parents=True)
    (publish / "app.toml").write_text(
        '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\n'
        'files = ["/app.py", "/helpers.py", "/.posit/publish/app.toml"]\n',
        encoding="utf-8",
    )
    selected = resolve_bundle_files(root, entrypoint="app.py")
    assert selected == [".posit/publish/app.toml", "app.py", "helpers.py"]


def test_resolve_bundle_files_honors_curation_by_exclusion(tmp_path):
    """``["*", "!x"]`` is curation too: everything *except* x.

    ``*`` alone means "no restriction", but ``*`` followed by a ``!`` exclusion is a
    deliberate, and natural, way to curate -- it must not be flattened away."""
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "helpers.py", "secrets.txt"])
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    (publish / "app.toml").write_text(
        '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\nfiles = ["*", "!/secrets.txt"]\n',
        encoding="utf-8",
    )
    selected = resolve_bundle_files(root, entrypoint="app.py")
    assert "app.py" in selected
    assert "helpers.py" in selected
    assert "secrets.txt" not in selected


def test_resolve_bundle_files_none_when_no_config(tmp_path):
    """Without a config there is no restriction at all: the caller keeps its
    long-standing whole-tree walk, so .gitignore is never consulted."""
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["app.py", "secret.log"])
    (tmp_path / ".gitignore").write_text("*.log\n", encoding="utf-8")
    assert resolve_bundle_files(root) is None


def test_no_config_bundles_gitignored_files(tmp_path):
    """A .gitignore'd build artifact (a Quarto project's rendered HTML, say) is
    still bundled when no config applies -- that output is exactly what deploys."""
    from rsconnect.bundle import create_file_list, restrict_to_files
    from rsconnect.publisher.store import resolve_bundle_files

    root = str(tmp_path)
    _make_tree(root, ["report.qmd", "_site/report.html"])
    (tmp_path / ".gitignore").write_text("_site/\n", encoding="utf-8")
    with restrict_to_files(resolve_bundle_files(root)):
        files = create_file_list(root, [], [])
    assert os.path.join("_site", "report.html") in files


# --- end-to-end: the executor resolves + restricts around the builder --------


def _make_config_restricted_project(tmp_path):
    root = str(tmp_path)
    _make_tree(root, ["app.py", "helpers.py", "requirements.txt"])
    publish = tmp_path / ".posit" / "publish"
    publish.mkdir(parents=True)
    (publish / "app.toml").write_text(
        '"$schema" = "x"\ntype = "python-shiny"\nentrypoint = "app.py"\nfiles = [\n    "/app.py",\n]\n',
        encoding="utf-8",
    )
    return root


def test_executor_make_bundle_uses_explicit_publisher_context(tmp_path):
    import io

    from rsconnect.api import PublisherContext, RSConnectExecutor
    from rsconnect.bundle import create_file_list
    from rsconnect.publisher.store import resolve_bundle_files

    root = _make_config_restricted_project(tmp_path)

    captured = {}

    def fake_builder(*_args, **_kwargs):
        # Inside make_bundle the restriction is active, so the shared walker sees
        # only the config's allowlisted files.
        captured["files"] = create_file_list(root, [], [])
        return io.BytesIO(b"bundle")

    # app_id set so make_deployment_name does not contact a server for a unique name.
    ce = RSConnectExecutor(
        path=root,
        app_id="1",
        publisher_context=PublisherContext(
            project_dir=root,
            config_name="app",
            record_name=None,
            include_files=resolve_bundle_files(root, config_name="app"),
            manifest_overlay={},
        ),
    )
    ce.make_bundle(fake_builder)

    assert captured["files"] == ["app.py"]


def test_executor_make_bundle_ignores_curation_by_default(tmp_path):
    """A plain deploy has no Publisher context and therefore bundles everything."""
    import io

    from rsconnect.api import RSConnectExecutor
    from rsconnect.bundle import create_file_list

    root = _make_config_restricted_project(tmp_path)

    captured = {}

    def fake_builder(*_args, **_kwargs):
        captured["files"] = create_file_list(root, [], [])
        return io.BytesIO(b"bundle")

    ce = RSConnectExecutor(path=root, app_id="1")
    ce.make_bundle(fake_builder)

    # the whole tree, including the config itself, since nothing restricts it
    assert captured["files"] == [
        os.path.join(".posit", "publish", "app.toml"),
        "app.py",
        "helpers.py",
        "requirements.txt",
    ]


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
    from rsconnect.api import PublisherContext, RSConnectExecutor
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

    ce = RSConnectExecutor(
        path=root,
        app_id="1",
        publisher_context=PublisherContext(
            project_dir=root,
            config_name="app",
            record_name=None,
            include_files=None,
            manifest_overlay={
                "integration_requests": [{"guid": "abc-123", "name": "My Snowflake", "type": "snowflake"}]
            },
        ),
    )
    ce.make_bundle(fake_builder)

    assert captured["manifest"]["integration_requests"][0]["guid"] == "abc-123"
