"""Integration tests for the ``rsconnect redeploy`` command.

Exercises the CLI via ``click.testing.CliRunner``, short-circuiting the deploy
at ``make_bundle`` (as ``tests/test_deploy_pyproject.py`` does) so the full
command wiring -- ``.posit`` resolution -> executor construction -> app_mode
dispatch -- runs without any network call. Asserts that the deployment record's
server and content identity are recovered and reused.
"""

from __future__ import annotations

import pathlib
import textwrap
import types
import typing

import pytest
from click.testing import CliRunner

from rsconnect.main import cli

SERVER_URL = "https://connect.example.com"
GUID = "RECORD-GUID-123"


@pytest.fixture(autouse=True)
def _isolate_connect_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Neutralize ambient Connect credentials so ``redeploy`` resolves the server
    and content identity from the ``.posit`` record rather than the environment.

    The integration-test CI job exports ``CONNECT_SERVER``/``CONNECT_API_KEY``
    (pointing at its throwaway Connect); without this those would leak through the
    ``--server``/``--api-key`` env-var options into the command under test and
    override the record-based resolution these tests assert on.
    """
    for var in (
        "CONNECT_SERVER",
        "CONNECT_API_KEY",
        "CONNECT_INSECURE",
        "CONNECT_CA_CERTIFICATE",
        "CONNECT_IDENTITY_TOKEN",
        "CONNECT_IDENTITY_TOKEN_FILE",
        "CONNECT_SERVER_VERSION",
    ):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


@pytest.fixture
def project_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path


def _write_posit_project(
    project_dir: pathlib.Path,
    *,
    server_url: str = SERVER_URL,
    guid: typing.Optional[str] = GUID,
    content_type: str = "python-shiny",
    entrypoint: str = "app.py",
    config_name: str = "app",
    with_record: bool = True,
) -> None:
    """Author a ``.posit/publish`` config (+ optional record) on disk."""
    publish = project_dir / ".posit" / "publish"
    deployments = publish / "deployments"
    deployments.mkdir(parents=True, exist_ok=True)

    (publish / f"{config_name}.toml").write_text(
        textwrap.dedent(
            f"""\
            "$schema" = "https://cdn.posit.co/publisher/schemas/posit-publishing-schema-v3.json"
            product_type = "connect"
            type = "{content_type}"
            entrypoint = "{entrypoint}"
            validate = true
            files = ["/{entrypoint}"]

            [python]
            version = "3.11"
            package_file = "requirements.txt"
            """
        )
    )
    if with_record:
        record_body = textwrap.dedent(
            f"""\
            "$schema" = "https://cdn.posit.co/publisher/schemas/posit-publishing-record-schema-v3.json"
            server_type = "connect"
            server_url = "{server_url}"
            type = "{content_type}"
            configuration_name = "{config_name}"
            """
        )
        if guid:
            record_body += f'id = "{guid}"\n'
        (deployments / "deployment-abc123.toml").write_text(record_body)

    if ":" not in entrypoint:
        (project_dir / entrypoint).touch()


def _spy_make_bundle(monkeypatch: pytest.MonkeyPatch) -> dict[str, typing.Any]:
    """Short-circuit the deploy at ``make_bundle`` and capture executor state."""
    captured: dict[str, typing.Any] = {}

    class _StopDispatch(Exception):
        pass

    def spy_make_bundle(
        self: typing.Any, builder: typing.Callable[..., typing.Any], *args: typing.Any, **kwargs: typing.Any
    ):
        captured["builder"] = builder.__name__
        captured["args"] = args
        captured["app_id"] = self.app_id
        captured["server_url"] = self.remote_server.url
        captured["app_mode"] = self.app_mode.name() if self.app_mode else None
        captured["title"] = self.title
        captured["publisher_config_name"] = self.publisher_config_name
        captured["publisher_record_name"] = self.publisher_record_name
        raise _StopDispatch()

    from rsconnect import api as api_mod
    from rsconnect import main as main_mod

    fake_environment = types.SimpleNamespace(python="python")
    monkeypatch.setattr(
        main_mod.Environment,
        "create_python_environment",
        classmethod(lambda cls, *args, **kwargs: fake_environment),
    )
    monkeypatch.setattr(api_mod.RSConnectClient, "server_settings", lambda self: {})
    monkeypatch.setattr(api_mod.RSConnectExecutor, "validate_server", lambda self: self)

    def fake_validate_app_mode(self: typing.Any, app_mode: typing.Any):
        self.app_mode = app_mode
        return self

    monkeypatch.setattr(api_mod.RSConnectExecutor, "validate_app_mode", fake_validate_app_mode)
    monkeypatch.setattr(api_mod.RSConnectExecutor, "make_bundle", spy_make_bundle)
    return captured


def test_redeploy_command_is_registered(runner: CliRunner):
    result = runner.invoke(cli, ["redeploy", "--help"])
    assert result.exit_code == 0
    assert ".posit/publish" in result.output


def test_redeploy_errors_without_posit_project(runner: CliRunner, project_dir: pathlib.Path):
    result = runner.invoke(cli, ["redeploy", str(project_dir)])
    assert result.exit_code != 0
    assert "No .posit/publish configuration" in result.output


def test_redeploy_errors_on_first_deploy_without_server(runner: CliRunner, project_dir: pathlib.Path):
    _write_posit_project(project_dir, with_record=False)
    result = runner.invoke(cli, ["redeploy", str(project_dir)])
    assert result.exit_code != 0
    assert "No prior deployment found" in result.output


def test_redeploy_reuses_identity_from_record(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    captured = _spy_make_bundle(monkeypatch)
    _write_posit_project(project_dir)

    result = runner.invoke(cli, ["redeploy", str(project_dir), "-k", "fake-key"])

    assert captured.get("builder") == "make_api_bundle", result.output
    # server and content identity recovered from the deployment record
    assert captured["server_url"] == SERVER_URL
    assert captured["app_id"] == GUID
    assert captured["app_mode"] == "python-shiny"
    # the resolved config/record filenames are pinned so save updates them in place
    assert captured["publisher_config_name"] == "app"
    assert captured["publisher_record_name"] == "deployment-abc123"


def test_redeploy_app_id_override(runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    captured = _spy_make_bundle(monkeypatch)
    _write_posit_project(project_dir)

    result = runner.invoke(cli, ["redeploy", str(project_dir), "-k", "fake-key", "--app-id", "OVERRIDE-999"])

    assert captured.get("builder") == "make_api_bundle", result.output
    assert captured["app_id"] == "OVERRIDE-999"


def test_redeploy_requires_config_name_when_multiple(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    _spy_make_bundle(monkeypatch)
    _write_posit_project(project_dir, config_name="one", with_record=False)
    _write_posit_project(project_dir, config_name="two", with_record=False)

    result = runner.invoke(cli, ["redeploy", str(project_dir), "-k", "fake-key"])
    assert result.exit_code != 0
    assert "Multiple .posit configs" in result.output


def test_redeploy_selects_config_by_name(runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    """--config-name disambiguates among multiple configs and picks that config's
    deployment record."""
    captured = _spy_make_bundle(monkeypatch)
    # Two configs; only "two" has a prior deployment record.
    _write_posit_project(project_dir, config_name="one", entrypoint="one.py", with_record=False)
    _write_posit_project(project_dir, config_name="two", entrypoint="two.py", with_record=True)

    result = runner.invoke(cli, ["redeploy", str(project_dir), "-k", "fake-key", "--config-name", "two"])

    assert captured.get("builder") == "make_api_bundle", result.output
    assert captured["app_id"] == GUID
    # dispatched with the selected config's entrypoint
    assert "two.py" in captured["args"], captured["args"]


def _write_legacy_project(
    project_dir: pathlib.Path,
    *,
    server_url: str = SERVER_URL,
    guid: str = GUID,
    appmode: str = "python-shiny",
    with_manifest: bool = True,
    with_legacy_json: bool = True,
) -> None:
    """Author pre-.posit artifacts: a manifest.json and/or a legacy JSON record."""
    import json

    if with_manifest:
        (project_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "metadata": {"appmode": appmode, "entrypoint": "app.py"},
                    "files": {"app.py": {"checksum": "x"}},
                }
            )
        )
    if with_legacy_json:
        legacy = project_dir / "rsconnect-python"
        legacy.mkdir(parents=True, exist_ok=True)
        (legacy / "app.json").write_text(
            json.dumps(
                {
                    server_url: {
                        "server_url": server_url,
                        "filename": str(project_dir / "app.py"),
                        "app_url": "https://connect.example.com/content/xyz/",
                        "app_id": "7",
                        "app_guid": guid,
                        "title": "Legacy App",
                        "app_mode": appmode,
                        "app_store_version": 1,
                    }
                }
            )
        )
    (project_dir / "app.py").touch()


def test_redeploy_legacy_fallback_manifest_and_json(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """With no .posit but a manifest.json + legacy JSON, redeploy deploys the
    manifest bundle to the recorded server/GUID."""
    captured = _spy_make_bundle(monkeypatch)
    _write_legacy_project(project_dir)

    result = runner.invoke(cli, ["redeploy", str(project_dir), "-k", "fake-key"])

    assert captured.get("builder") == "make_manifest_bundle", result.output
    assert captured["app_id"] == GUID
    assert captured["server_url"] == SERVER_URL


def test_redeploy_legacy_requires_manifest(runner: CliRunner, project_dir: pathlib.Path):
    """Legacy JSON without a manifest.json has nothing to build from."""
    _write_legacy_project(project_dir, with_manifest=False)
    result = runner.invoke(cli, ["redeploy", str(project_dir)])
    assert result.exit_code != 0
    assert "nothing to redeploy" in result.output


def test_redeploy_legacy_manifest_without_record_needs_server(runner: CliRunner, project_dir: pathlib.Path):
    """A manifest with no prior deployment record is a first deploy."""
    _write_legacy_project(project_dir, with_legacy_json=False)
    result = runner.invoke(cli, ["redeploy", str(project_dir)])
    assert result.exit_code != 0
    assert "No prior deployment found" in result.output


def test_find_saved_server_by_url_matches_normalized(monkeypatch: pytest.MonkeyPatch):
    from rsconnect import main as main_mod

    saved = [{"name": "prod", "url": "https://connect.example.com/__api__"}]
    monkeypatch.setattr(main_mod, "server_store", types.SimpleNamespace(get_all_servers=lambda: saved))

    # trailing slash / __api__ differences still match
    assert main_mod._find_saved_server_by_url("https://connect.example.com/")["name"] == "prod"
    assert main_mod._find_saved_server_by_url("https://other.example.com") is None
    assert main_mod._find_saved_server_by_url(None) is None


def test_find_saved_server_by_url_ambiguous_raises(monkeypatch: pytest.MonkeyPatch):
    """Two saved credentials for the same server must not be guessed between."""
    from rsconnect import main as main_mod
    from rsconnect.exception import RSConnectException

    saved = [
        {"name": "prod-a", "url": "https://connect.example.com"},
        {"name": "prod-b", "url": "https://connect.example.com/__api__"},
    ]
    monkeypatch.setattr(main_mod, "server_store", types.SimpleNamespace(get_all_servers=lambda: saved))

    with pytest.raises(RSConnectException, match="Multiple saved servers match"):
        main_mod._find_saved_server_by_url("https://connect.example.com/")


def test_redeploy_reuses_saved_credential_by_url(
    runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch
):
    """With no explicit credential, redeploy matches the record's server_url to a
    saved rsconnect-python server (normalized) and deploys under that nickname."""
    from rsconnect import main as main_mod

    saved = {"name": "prod", "url": "https://connect.example.com/__api__/"}
    monkeypatch.setattr(
        main_mod,
        "server_store",
        types.SimpleNamespace(get_all_servers=lambda: [saved], get_by_name=lambda n: saved if n == "prod" else None),
    )

    captured: dict[str, typing.Any] = {}

    class FakeExecutor:
        def __init__(self, **kwargs: typing.Any):
            captured.update(kwargs)
            self.client = None
            self.supports_verify_before_activate = False

        def __getattr__(self, _name: str):
            # every fluent step is a no-op that returns self
            return lambda *a, **k: self

        def should_deploy_as_draft(self, *a: typing.Any, **k: typing.Any) -> bool:
            return False

    monkeypatch.setattr(main_mod, "RSConnectExecutor", FakeExecutor)
    monkeypatch.setattr(main_mod, "prepare_deploy_metadata", lambda *a, **k: None)
    fake_env = types.SimpleNamespace(python="python")
    monkeypatch.setattr(main_mod.Environment, "create_python_environment", classmethod(lambda cls, *a, **k: fake_env))
    _write_posit_project(project_dir)  # record server_url = https://connect.example.com

    result = runner.invoke(cli, ["redeploy", str(project_dir)])

    assert result.exit_code == 0, result.output
    # matched the saved server: deploy under its nickname, no raw server URL
    assert captured.get("name") == "prod"
    assert captured.get("server") is None


def test_redeploy_dispatches_quarto(runner: CliRunner, project_dir: pathlib.Path, monkeypatch: pytest.MonkeyPatch):
    captured = _spy_make_bundle(monkeypatch)
    from rsconnect import main as main_mod

    monkeypatch.setattr(main_mod, "which_quarto", lambda quarto=None: "quarto")
    monkeypatch.setattr(main_mod, "quarto_inspect", lambda quarto, path: {"engines": []})
    monkeypatch.setattr(main_mod, "validate_quarto_engines", lambda inspect: [])
    _write_posit_project(project_dir, content_type="quarto-static", entrypoint="report.qmd", config_name="report")

    result = runner.invoke(cli, ["redeploy", str(project_dir), "-k", "fake-key"])

    assert captured.get("builder") == "create_quarto_deployment_bundle", result.output
    assert captured["app_id"] == GUID
