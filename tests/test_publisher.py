"""Tests for the ``rsconnect.publisher`` .posit/publish TOML interop package."""

import io
import json
import tarfile

import pytest

from rsconnect.models import AppModes
from rsconnect.publisher import config, record, schema, serialize, store


# --- helpers ---------------------------------------------------------------


def make_bundle(manifest, extra_members=None):
    """Build an in-memory ``.tar.gz`` bundle with the given manifest dict."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        members = {"manifest.json": json.dumps(manifest)}
        members.update(extra_members or {})
        for name, text in members.items():
            data = text.encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf


PY_SHINY_MANIFEST = {
    "version": 1,
    "metadata": {"appmode": "python-shiny", "entrypoint": "app.py"},
    "files": {"app.py": {"checksum": "a"}, "requirements.txt": {"checksum": "b"}, "helpers.py": {"checksum": "c"}},
    "python": {"version": "3.11.5", "package_manager": {"name": "pip", "package_file": "requirements.txt"}},
    "environment": {"python": {"requires": ">=3.9"}},
}

DEPLOYED_INFO = {
    "app_guid": "GUID-123",
    "app_id": "7",
    "app_url": "https://connect.example.com/content/abc/",
    "dashboard_url": "https://connect.example.com/connect/#/apps/abc",
    "bundle_id": "42",
    "title": "My App",
}


def deploy(project_dir, server_url="https://connect.example.com/__api__", **overrides):
    info = {**DEPLOYED_INFO, **overrides}
    bundle = make_bundle(PY_SHINY_MANIFEST, {"requirements.txt": "# a comment\nshiny==1.0\n\nhtmltools>=0.5\n"})
    return store.write_deployment_metadata(
        project_dir=project_dir,
        server_url=server_url,
        product_type="connect",
        app_mode=AppModes.PYTHON_SHINY,
        title="My App",
        deployed_info=info,
        bundle=bundle,
    )


# --- type map --------------------------------------------------------------


def test_every_app_mode_maps_to_a_valid_publisher_type():
    valid_types = set(schema.TYPE_TO_APP_MODE) | {"unknown"}
    for mode in AppModes._modes:
        content_type = schema.type_from_app_mode(mode)
        assert content_type in valid_types, (mode.name(), content_type)


def test_app_mode_type_round_trips_except_tensorflow():
    for mode in AppModes._modes:
        content_type = schema.type_from_app_mode(mode)
        if mode is AppModes.TENSORFLOW:
            # TensorFlow has no Publisher content type.
            assert content_type == "unknown"
            continue
        assert schema.app_mode_from_type(content_type).name() == mode.name()


def test_known_type_translations():
    assert schema.type_from_app_mode(AppModes.PYTHON_API) == "python-flask"
    assert schema.type_from_app_mode(AppModes.PLUMBER) == "r-plumber"
    assert schema.type_from_app_mode(AppModes.SHINY) == "r-shiny"
    assert schema.type_from_app_mode(AppModes.RMD) == "rmd"
    assert schema.type_from_app_mode(AppModes.STATIC) == "html"
    # Publisher's deprecated "quarto" type resolves to the quarto-static app mode.
    assert schema.app_mode_from_type("quarto") is AppModes.STATIC_QUARTO


# --- serialization ---------------------------------------------------------


def test_schema_key_is_quoted_and_first(tmp_path):
    path = str(tmp_path / "c.toml")
    serialize.write(path, serialize.dumps({"$schema": "https://x", "type": "python-shiny", "files": ["/a", "/b"]}))
    text = open(path).read()
    assert text.splitlines()[0] == '"$schema" = "https://x"'
    # arrays are multiline, matching Publisher's output.
    assert "files = [\n    " in text


def test_prune_drops_none_and_empty_strings_keeps_false():
    dumped = serialize.dumps({"a": None, "b": "", "c": False, "d": 0, "e": "x"})
    assert "a =" not in dumped and "b =" not in dumped
    assert "c = false" in dumped and "d = 0" in dumped and 'e = "x"' in dumped


# --- write side ------------------------------------------------------------


def test_write_deployment_metadata_creates_config_and_record(tmp_path):
    project = str(tmp_path)
    config_path, record_path = deploy(project)

    cfg = config.read_config(config_path)
    assert cfg.type == "python-shiny"
    assert cfg.entrypoint == "app.py"
    assert cfg.title == "My App"
    assert cfg.validate is True
    # files is "everything" -- not a snapshot of the deployed set, which would
    # silently pin the content on the next deploy -- plus the driving .posit
    # config + record (mirrors Publisher).
    assert cfg.files[0] == "*"
    posit_files = [f for f in cfg.files if f.startswith("/.posit/publish/")]
    assert len(posit_files) == 2
    assert any("/deployments/" in f for f in posit_files)
    assert cfg.python == {
        "version": "3.11.5",
        "package_file": "requirements.txt",
        "package_manager": "pip",
        "requires_python": ">=3.9",
    }

    rec = record.read_record(record_path)
    assert rec.id == "GUID-123"
    assert rec.server_type == "connect"
    assert rec.type == "python-shiny"
    # configuration_name links to the config file that was written
    assert config_path.endswith(rec.configuration_name + ".toml")
    assert rec.direct_url == DEPLOYED_INFO["app_url"]
    assert rec.dashboard_url == DEPLOYED_INFO["dashboard_url"]
    assert rec.logs_url == DEPLOYED_INFO["dashboard_url"] + "/logs"
    assert rec.bundle_id == "42"
    # concrete manifest file list, sorted; requirements from requirements.txt (no comments/blanks)
    assert rec.files == ["app.py", "helpers.py", "requirements.txt"]
    assert rec.requirements == ["shiny==1.0", "htmltools>=0.5"]
    # embedded configuration snapshot matches the config file
    assert rec.config().type == "python-shiny"


def test_config_files_reference_the_record_that_was_written(tmp_path):
    """The ``.posit`` record path recorded in the config's ``files`` must be the
    record actually written, so the next deploy bundles it instead of a
    never-existing name."""
    import os

    project = str(tmp_path)
    config_path, record_path = deploy(project)

    cfg = config.read_config(config_path)
    recorded = [f for f in cfg.files if "/deployments/" in f]
    assert len(recorded) == 1
    assert os.path.basename(recorded[0]) == os.path.basename(record_path)
    # only one record file exists -- no orphaned second name was minted
    assert len(record.discover_records(project)) == 1
    # every .posit path in files resolves to a real file
    for rel in (f for f in cfg.files if f.startswith("/.posit/")):
        assert os.path.isfile(os.path.join(project, rel.lstrip("/"))), rel


def test_config_files_do_not_snapshot_the_deployed_set(tmp_path):
    """``files`` must not enumerate the files that happened to deploy.

    A snapshot reads as user curation on the next deploy, which would pin the
    content to that set and silently drop anything added later. The deployed set
    is still recorded on the *record* (see
    ``test_write_deployment_metadata_creates_config_and_record``)."""
    project = str(tmp_path)
    config_path, _ = deploy(project)
    cfg = config.read_config(config_path)
    content_patterns = [f for f in cfg.files if not f.startswith("/.posit/")]
    assert content_patterns == ["*"]


def test_config_files_omit_a_non_path_entrypoint(tmp_path):
    """A manifest ``metadata.entrypoint`` may be a module reference rather than a
    file (Shiny records ``app`` for ``app.py``); it must never leak into ``files``
    as a never-matching ``/app`` include."""
    manifest = {
        **PY_SHINY_MANIFEST,
        # what rsconnect actually writes for a `deploy shiny` of app.py
        "metadata": {"appmode": "python-shiny", "entrypoint": "app"},
    }
    bundle = make_bundle(manifest, {"requirements.txt": "shiny==1.0\n"})
    config_path, _ = store.write_deployment_metadata(
        project_dir=str(tmp_path),
        server_url="https://connect.example.com/__api__",
        product_type="connect",
        app_mode=AppModes.PYTHON_SHINY,
        title="My App",
        deployed_info=DEPLOYED_INFO,
        bundle=bundle,
    )
    cfg = config.read_config(config_path)
    assert "/app" not in cfg.files
    # the entrypoint is still recorded as the config's entrypoint, verbatim
    assert cfg.entrypoint == "app"


def test_redeploy_pins_resolved_config_and_record(tmp_path):
    """Passing config_name/record_name (as redeploy does) updates those exact
    files, even when the record lacks a configuration_name and the config's
    entrypoint differs from the bundle -- preventing duplicate config/record files.
    """
    import os

    project = str(tmp_path)
    publish = tmp_path / ".posit" / "publish"
    (publish / "deployments").mkdir(parents=True)
    # config entrypoint deliberately differs from the bundle manifest's "app.py"
    (publish / "chosen.toml").write_text(
        '"$schema" = "https://cdn.posit.co/publisher/schemas/posit-publishing-schema-v3.json"\n'
        'product_type = "connect"\n'
        'type = "python-shiny"\n'
        'entrypoint = "different.py"\n'
        "validate = true\n"
        'files = ["/different.py"]\n'
    )
    # record with NO configuration_name -> auto-derivation would miss the config
    (publish / "deployments" / "chosen-rec.toml").write_text(
        '"$schema" = "https://cdn.posit.co/publisher/schemas/posit-publishing-record-schema-v3.json"\n'
        'server_type = "connect"\n'
        'server_url = "https://connect.example.com"\n'
        'type = "python-shiny"\n'
    )

    bundle = make_bundle(PY_SHINY_MANIFEST, {"requirements.txt": "shiny\n"})
    store.write_deployment_metadata(
        project_dir=project,
        server_url="https://connect.example.com",
        product_type="connect",
        app_mode=AppModes.PYTHON_SHINY,
        title="My App",
        deployed_info=DEPLOYED_INFO,
        bundle=bundle,
        config_name="chosen",
        record_name="chosen-rec",
    )

    assert {os.path.basename(p) for p in config.discover_configs(project)} == {"chosen.toml"}
    assert {os.path.basename(p) for p in record.discover_records(project)} == {"chosen-rec.toml"}
    rec = record.read_record(record.discover_records(project)[0])
    assert rec.configuration_name == "chosen"
    assert rec.id == "GUID-123"


def test_filenames_use_publisher_random_code_methodology(tmp_path):
    """rsconnect mints the same style of names as Publisher's names.ts: a config
    ``<filenamified-title>-<CODE>`` and a record ``deployment-<CODE>``, where CODE
    is a 4-char uppercase base-32 string."""
    import os
    import re

    config_path, record_path = deploy(str(tmp_path))
    config_stem = os.path.splitext(os.path.basename(config_path))[0]
    record_stem = os.path.splitext(os.path.basename(record_path))[0]

    # title "My App" -> filenamify keeps it; 4-char base-32 (0-9, A-V) ending
    assert re.fullmatch(r"My App-[0-9A-V]{4}", config_stem), config_stem
    assert re.fullmatch(r"deployment-[0-9A-V]{4}", record_stem), record_stem


def test_redeploy_updates_in_place(tmp_path):
    project = str(tmp_path)
    config_path, record_path = deploy(project)
    # a cosmetically different URL still maps to the same record file
    config_path2, record_path2 = deploy(project, server_url="https://connect.example.com", bundle_id="43")
    assert config_path2 == config_path
    assert record_path2 == record_path
    assert len(record.discover_records(project)) == 1
    assert len(config.discover_configs(project)) == 1
    assert record.read_record(record_path2).bundle_id == "43"


def test_created_at_preserved_on_redeploy(tmp_path):
    project = str(tmp_path)
    _, record_path = deploy(project)
    first = record.read_record(record_path).created_at
    _, record_path = deploy(project, bundle_id="99")
    assert record.read_record(record_path).created_at == first


def test_snowflake_product_type(tmp_path):
    bundle = make_bundle(PY_SHINY_MANIFEST, {"requirements.txt": "shiny\n"})
    _, record_path = store.write_deployment_metadata(
        project_dir=str(tmp_path),
        server_url="https://acct.snowflakecomputing.app",
        product_type=schema.PRODUCT_TYPE_SNOWFLAKE,
        app_mode=AppModes.PYTHON_SHINY,
        title="x",
        deployed_info=DEPLOYED_INFO,
        bundle=bundle,
    )
    assert record.read_record(record_path).server_type == "snowflake"


# --- read side / resolve ---------------------------------------------------


def test_resolve_single(tmp_path):
    project = str(tmp_path)
    deploy(project)
    target = store.resolve_publisher_deploy_target(project)
    assert target.app_mode is AppModes.PYTHON_SHINY
    assert target.entrypoint == "app.py"
    assert target.app_id == "GUID-123"
    assert target.requirements_file == "requirements.txt"
    assert target.server_url is not None


def test_resolve_url_normalization(tmp_path):
    project = str(tmp_path)
    deploy(project, server_url="https://connect.example.com/__api__")
    # match despite missing __api__ and trailing slash
    target = store.resolve_publisher_deploy_target(project, server="https://connect.example.com/")
    assert target.app_id == "GUID-123"


def test_resolve_no_config_raises(tmp_path):
    from rsconnect.exception import RSConnectException

    with pytest.raises(RSConnectException, match="No .posit/publish configuration"):
        store.resolve_publisher_deploy_target(str(tmp_path))


def test_resolve_multiple_configs_requires_name(tmp_path):
    from rsconnect.exception import RSConnectException

    project = str(tmp_path)
    config.write_config(project, "one", config.PublisherConfig(type="python-shiny", entrypoint="a.py"))
    config.write_config(project, "two", config.PublisherConfig(type="python-shiny", entrypoint="b.py"))
    with pytest.raises(RSConnectException, match="Multiple .posit configs"):
        store.resolve_publisher_deploy_target(project)
    # disambiguated by name
    target = store.resolve_publisher_deploy_target(project, config_name="two")
    assert target.entrypoint == "b.py"
    assert target.record is None  # no deployment yet


# --- interop with a Publisher-authored project -----------------------------


def test_reads_publisher_authored_project(tmp_path):
    """A config + record written by Publisher (random filenames, quoted $schema,
    connect_cloud table) must resolve and reuse the recorded content id."""
    publish = tmp_path / ".posit" / "publish"
    deployments = publish / "deployments"
    deployments.mkdir(parents=True)

    (publish / "my-app-AB12.toml").write_text(
        '"$schema" = "https://cdn.posit.co/publisher/schemas/posit-publishing-schema-v3.json"\n'
        'product_type = "connect"\n'
        'type = "python-shiny"\n'
        'entrypoint = "app.py"\n'
        "validate = true\n"
        'files = ["/app.py"]\n\n'
        "[python]\n"
        'version = "3.11"\n'
        'package_file = "requirements.txt"\n'
    )
    (deployments / "deployment-CD34.toml").write_text(
        "# This file is automatically generated by Posit Publisher; do not edit.\n"
        '"$schema" = "https://cdn.posit.co/publisher/schemas/posit-publishing-record-schema-v3.json"\n'
        'server_type = "connect"\n'
        'server_url = "https://connect.example.com"\n'
        'type = "python-shiny"\n'
        'id = "PUBLISHER-GUID"\n'
        'configuration_name = "my-app-AB12"\n'
    )

    target = store.resolve_publisher_deploy_target(str(tmp_path))
    assert target.config_name == "my-app-AB12"
    assert target.app_mode is AppModes.PYTHON_SHINY
    assert target.entrypoint == "app.py"
    assert target.app_id == "PUBLISHER-GUID"
    assert target.requirements_file == "requirements.txt"


def test_write_config_from_manifest(tmp_path):
    project = str(tmp_path)
    path = store.write_config_from_manifest(project, PY_SHINY_MANIFEST)
    cfg = config.read_config(path)
    assert cfg.type == "python-shiny"
    assert cfg.entrypoint == "app.py"
    # "everything", plus the config file itself (mirrors Publisher). No record
    # path: write-manifest does not deploy.
    assert cfg.files[0] == "*"
    assert any(f.startswith("/.posit/publish/") and f.endswith(".toml") for f in cfg.files)
    assert not any("/deployments/" in f for f in cfg.files)
    # write-manifest prepares content but does not deploy: no record is written.
    assert record.discover_records(project) == []


def test_write_manifest_publisher_config_helper(tmp_path):
    """The write-manifest CLI helper writes a config next to an existing
    manifest.json, using the explicit app_mode (not the manifest's appmode)."""
    import json as _json

    from rsconnect.main import _write_manifest_publisher_config

    (tmp_path / "manifest.json").write_text(_json.dumps(PY_SHINY_MANIFEST))
    _write_manifest_publisher_config(str(tmp_path), AppModes.PYTHON_SHINY)

    configs = config.discover_configs(str(tmp_path))
    assert len(configs) == 1
    cfg = config.read_config(configs[0])
    assert cfg.type == "python-shiny"
    assert cfg.entrypoint == "app.py"
    # no record: write-manifest does not deploy
    assert record.discover_records(str(tmp_path)) == []


def test_write_manifest_publisher_config_skips_unknown_type(tmp_path):
    """TensorFlow has no Publisher content type, so no config is written."""
    import json as _json

    from rsconnect.main import _write_manifest_publisher_config

    (tmp_path / "manifest.json").write_text(_json.dumps(PY_SHINY_MANIFEST))
    _write_manifest_publisher_config(str(tmp_path), AppModes.TENSORFLOW)
    assert config.discover_configs(str(tmp_path)) == []


def test_connect_cloud_round_trip(tmp_path):
    project = str(tmp_path)
    cfg = config.PublisherConfig(
        type="python-shiny",
        entrypoint="app.py",
        product_type=schema.PRODUCT_TYPE_CONNECT_CLOUD,
        connect_cloud={"vanity_name": "my-app", "access_control": {"public_access": True}},
    )
    path, _ = config.write_config(project, "cloud", cfg)
    reread = config.read_config(path)
    assert reread.product_type == "connect_cloud"
    assert reread.connect_cloud["vanity_name"] == "my-app"

    # rsconnect defaults product_type to connect, but must not downgrade an
    # existing connect_cloud config on rewrite.
    config.write_config(project, "cloud", config.PublisherConfig(type="python-shiny", entrypoint="app.py"))
    assert config.read_config(path).product_type == "connect_cloud"
    assert config.read_config(path).connect_cloud["vanity_name"] == "my-app"
