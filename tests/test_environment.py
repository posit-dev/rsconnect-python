import re
import sys
import os
import json
import tempfile
import shutil
import subprocess
import zipfile
from pathlib import Path
from unittest import TestCase
from unittest import mock

import rsconnect.environment
from rsconnect.exception import RSConnectException
from rsconnect.environment import Environment, PackageInstaller, which_python
from rsconnect.subprocesses.inspect_environment import (
    EnvironmentException,
    detect_environment,
    check_editables_are_bundleable,
    filter_pip_freeze_output,
    rsconnect_project_dir,
    get_default_locale,
    get_python_version,
)

from .utils import get_dir

import pytest
import uv

version_re = re.compile(r"\d+\.\d+(\.\d+)?")
TESTDATA = os.path.join(os.path.dirname(__file__), "testdata")


class TestEnvironment(TestCase):
    @staticmethod
    def python_version():
        return ".".join(map(str, sys.version_info[:3]))

    def test_get_python_version(self):
        self.assertEqual(
            get_python_version(),
            self.python_version(),
        )

    def test_get_default_locale(self):
        self.assertEqual(get_default_locale(lambda: ("en_US", "UTF-8")), "en_US.UTF-8")
        self.assertEqual(get_default_locale(lambda: (None, "UTF-8")), ".UTF-8")
        self.assertEqual(get_default_locale(lambda: ("en_US", None)), "en_US.")
        self.assertEqual(get_default_locale(lambda: (None, None)), "")

    def test_file(self):
        directory = get_dir("pip1")
        result = Environment.create_python_environment(directory)

        self.assertTrue(version_re.match(result.pip))

        self.assertIsInstance(result.locale, str)
        self.assertIn(".", result.locale)

        expected = Environment.from_dict(
            dict(
                contents=Path(directory, "requirements.txt").read_bytes().decode("utf-8"),
                filename="requirements.txt",
                locale=result.locale,
                package_manager="pip",
                pip=result.pip,
                python=self.python_version(),
                source="file",
            ),
            python_interpreter=sys.executable,
            python_version_requirement=">=3.8",
        )
        self.assertEqual(expected, result)

    def test_requirements_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            project_dir = os.path.join(tmpdir, "project")
            shutil.copytree(get_dir("pip1"), project_dir)
            os.makedirs(os.path.join(project_dir, "alt"), exist_ok=True)
            custom_requirements = os.path.join(project_dir, "alt", "custom.txt")
            with open(custom_requirements, "w", newline="\n") as f:
                f.write("foo==1.0\nbar>=2.0\nrsconnect-python==0.1\nrsconnect==0.1\n")

            result = Environment.create_python_environment(
                project_dir, requirements_file=os.path.join("alt", "custom.txt")
            )

            assert result.filename.endswith("custom.txt")
            assert result.contents == "foo==1.0\nbar>=2.0\n"
            assert result.source == "file"

    def test_pip_freeze(self):
        result = Environment.create_python_environment(get_dir("pip2"), requirements_file=None)

        # these are the dependencies declared in our pyproject.toml
        self.assertIn("six", result.contents)
        self.assertIn("click", result.contents.lower())

        self.assertTrue(version_re.match(result.pip))

        self.assertIsInstance(result.locale, str)
        self.assertIn(".", result.locale)

        expected = Environment.from_dict(
            dict(
                contents=result.contents,
                filename="requirements.txt",
                locale=result.locale,
                package_manager="pip",
                pip=result.pip,
                python=self.python_version(),
                source="pip_freeze",
            ),
            python_interpreter=sys.executable,
        )
        self.assertEqual(expected, result)

    def test_filter_pip_freeze_output(self):
        raw_stdout = "numpy\npandas\n[notice] A new release of pip is available: 23.1.2 -> 23.3\n\
[notice] To update, run: pip install --upgrade pip"
        filtered = filter_pip_freeze_output(raw_stdout)
        expected = "numpy\npandas"

        self.assertEqual(filtered, expected)

        raw_stdout = "numpy\npandas"
        filtered = filter_pip_freeze_output(raw_stdout)
        expected = "numpy\npandas"

        self.assertEqual(filtered, expected)

        raw_stdout = "numpy\npandas\nnot at beginning [notice]\n\
[notice] To update, run: pip install --upgrade pip"
        filtered = filter_pip_freeze_output(raw_stdout)
        expected = "numpy\npandas\nnot at beginning [notice]"

        self.assertEqual(filtered, expected)


def test_filter_generated_requirements():
    raw = "\n".join(
        [
            "rsconnect-python==1.0",
            "rsconnect==1.0",
            "RSCONNECT @ https://example.com/rsconnect.whl",
            "RSCONNECT_PYTHON @ https://example.com/rsconnect.whl",
            "rsconnect.python>=1",
            "rsconnect-python",
            "  Rsconnect_-Python[extra] ; python_version >= '3.8'",
            "-rsconnect-python",
            "my-rsconnect-utils==0.1",
            "rsconnect-utils==0.1",
            "rsconnect-python-extra==1.0",
            "demo @ file:///work/rsconnect-demo",
            "# Editable install with no version control (demo==1.0)",
            "-e git+https://example.com/repo.git#egg=remote",
            "-e git+ssh://git@example.com/repo.git#egg=remote-ssh",
            "-e bzr+lp:project#egg=remote-bzr",
            "-e git+https:repo#egg=remote-git",
            "-e hg+http://example.com/repo#egg=remote-hg",
            "--editable=svn+svn://example.com/repo#egg=remote-svn",
            "-e https://example.com/project.tar.gz#egg=remote-archive",
            "# my rsconnect project",
        ]
    )

    assert filter_pip_freeze_output(raw).splitlines() == [
        "-rsconnect-python",
        "my-rsconnect-utils==0.1",
        "rsconnect-utils==0.1",
        "rsconnect-python-extra==1.0",
        "demo @ file:///work/rsconnect-demo",
        "-e git+https://example.com/repo.git#egg=remote",
        "-e git+ssh://git@example.com/repo.git#egg=remote-ssh",
        "-e bzr+lp:project#egg=remote-bzr",
        "-e git+https:repo#egg=remote-git",
        "-e hg+http://example.com/repo#egg=remote-hg",
        "--editable=svn+svn://example.com/repo#egg=remote-svn",
        "-e https://example.com/project.tar.gz#egg=remote-archive",
        "# my rsconnect project",
    ]


@pytest.mark.parametrize(
    "requirement",
    [
        "-e /work/rsconnect-demo",
        "-e ../outside-project",
        "-e ./libs/../../outside-project",
        "--editable=file:///work/project",
        "-e git+file:///work/repo#egg=project",
        "-e git+file:/work/repo#egg=project",
        "-e C:\\work\\project",
        "-e D:/work/project",
        "-e FILE:///work/project",
    ],
)
def test_check_editables_rejects_editables_outside_bundle(tmp_path: Path, requirement):
    with pytest.raises(EnvironmentException) as error:
        check_editables_are_bundleable(f"six==1.17.0\n{requirement}\n", str(tmp_path))

    assert requirement in str(error.value)
    assert "requirements file" in str(error.value)


@pytest.mark.parametrize(
    "requirement",
    [
        "-e ./libs/foo",
        "-e libs/foo",
        "--editable=.",
        "-e git+https://example.com/repo.git#egg=remote",
        "-e bzr+lp:project#egg=remote-bzr",
        "six @ file:///work/six",
    ],
)
def test_check_editables_allows_bundleable_requirements(tmp_path: Path, requirement):
    check_editables_are_bundleable(f"{requirement}\r\n", str(tmp_path))


def test_filter_generated_requirements_drops_editable_rsconnect():
    raw = "\n".join(
        [
            "six==1.17.0",
            "-e git+https://github.com/posit-dev/rsconnect-python.git@abc123#egg=rsconnect_python",
            "-e git+https://example.com/rsconnect.git#egg=RSCONNECT",
            "-e git+https://example.com/rsconnect-utils.git#egg=rsconnect-utils",
            "# Editable install with no version control (rsconnect-python==1.0)",
            f"-e {rsconnect_project_dir}",
        ]
    )

    assert filter_pip_freeze_output(raw) == (
        "six==1.17.0\n-e git+https://example.com/rsconnect-utils.git#egg=rsconnect-utils"
    )


def test_check_editables_reports_all_unbundleable_editables(tmp_path: Path):
    with pytest.raises(EnvironmentException) as error:
        check_editables_are_bundleable("-e /work/one\n-e /work/two", str(tmp_path))

    assert "-e /work/one" in str(error.value)
    assert "-e /work/two" in str(error.value)


def missing_bundled_uv():
    raise FileNotFoundError("uv")


def make_environment_with_fake_pip(tmp_path: Path, version: str):
    env_dir = tmp_path / "env"
    subprocess.run([uv.find_uv_bin(), "venv", "--python", sys.executable, str(env_dir)], check=True)
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = Path(
        subprocess.check_output(
            [str(python), "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
        ).strip()
    )
    pip_dir = site / "pip"
    pip_dir.mkdir()
    (pip_dir / "__init__.py").write_text("")
    (pip_dir / "__main__.py").write_text(
        "import sys\n"
        "if '--version' in sys.argv:\n"
        f"    print('pip {version}')\n"
        "else:\n"
        "    assert '--exclude' in sys.argv and 'rsconnect-python' in sys.argv and 'rsconnect' in sys.argv\n"
        "    print('# Editable install with no version control (demo==1.0)')\n"
        "    print('-e /work/demo')\n"
    )
    return python, site


def test_inspect_environment_reports_local_editable(tmp_path: Path):
    python, _ = make_environment_with_fake_pip(tmp_path, "20.3")

    with pytest.raises(
        RSConnectException,
        match="Editable dependencies outside the deployment directory cannot be installed on Connect",
    ) as error:
        Environment._inspect_environment(str(python), str(tmp_path), requirements_file=None)

    assert "-e /work/demo" in str(error.value)
    assert "requirements file" in str(error.value)


def test_inspect_environment_uses_uv_for_old_pip(tmp_path: Path):
    python, site = make_environment_with_fake_pip(tmp_path, "20.2.4")
    package = site / "demo_package-1.0.dist-info"
    package.mkdir()
    (package / "METADATA").write_text("Metadata-Version: 2.1\nName: demo-package\nVersion: 1.0\n")

    environment = Environment._inspect_environment(str(python), str(tmp_path), requirements_file=None)

    assert environment.pip == "20.2.4"
    assert "demo-package==1.0" in environment.contents.splitlines()


def test_requirements_file_filters_only_rsconnect_distribution(tmp_path: Path):
    (tmp_path / "requirements.txt").write_bytes(
        b"RSCONNECT_PYTHON==1.0\r\nrsconnect==1.0\r\nmy-rsconnect-utils==0.1\r\n"
        b"demo @ file:///work/rsconnect-demo\r\n# rsconnect note\r\n-e ./libs/local\r\n"
    )

    env = Environment.create_python_environment(str(tmp_path))

    assert env.contents == "my-rsconnect-utils==0.1\r\ndemo\r\n# rsconnect note\r\n-e ./libs/local\r\n"


def test_requirements_file_rejects_editable_outside_bundle(tmp_path: Path):
    (tmp_path / "requirements.txt").write_text("six\n-e /Users/me/localpkg\n")

    with pytest.raises(
        RSConnectException,
        match="Editable dependencies outside the deployment directory cannot be installed on Connect",
    ) as error:
        Environment.create_python_environment(str(tmp_path))

    assert "-e /Users/me/localpkg" in str(error.value)


@pytest.mark.parametrize("fallback", [False, True])
def test_uv_lock_export(tmp_path, monkeypatch, fallback):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text(
        "[project]\nname='demo'\nversion='0.0.0'\n"
        "dependencies=['aiofiles==24.1.0','annotated-doc==0.0.4','annotated-types==0.7.0']\n",
        encoding="utf-8",
    )
    (project_dir / "uv.lock").write_text(
        """version = 1
revision = 3
requires-python = ">=3.11.3"

[[package]]
name = "aiofiles"
version = "24.1.0"
source = { registry = "https://pypi.org/simple" }
[package.sdist]
url = "https://example.com/aiofiles-24.1.0.tar.gz"
hash = "sha256:1111111111111111111111111111111111111111111111111111111111111111"
[[package.wheels]]
url = "https://example.com/aiofiles-24.1.0-py3-none-any.whl"
hash = "sha256:2222222222222222222222222222222222222222222222222222222222222222"

[[package]]
name = "annotated-doc"
version = "0.0.4"
source = { registry = "https://pypi.org/simple" }
[package.sdist]
url = "https://example.com/annotated_doc-0.0.4.tar.gz"
hash = "sha256:3333333333333333333333333333333333333333333333333333333333333333"
[[package.wheels]]
url = "https://example.com/annotated_doc-0.0.4-py3-none-any.whl"
hash = "sha256:4444444444444444444444444444444444444444444444444444444444444444"

[[package]]
name = "annotated-types"
version = "0.7.0"
source = { registry = "https://pypi.org/simple" }
[package.sdist]
url = "https://example.com/annotated_types-0.7.0.tar.gz"
hash = "sha256:5555555555555555555555555555555555555555555555555555555555555555"
[[package.wheels]]
url = "https://example.com/annotated_types-0.7.0-py3-none-any.whl"
hash = "sha256:6666666666666666666666666666666666666666666666666666666666666666"

[[package]]
name = "demo"
version = "0.0.0"
source = { virtual = "." }
dependencies = [
    { name = "aiofiles" },
    { name = "annotated-doc" },
    { name = "annotated-types" },
]

[package.metadata]
requires-dist = [
    { name = "aiofiles", specifier = "==24.1.0" },
    { name = "annotated-doc", specifier = "==0.0.4" },
    { name = "annotated-types", specifier = "==0.7.0" },
]""",
        encoding="utf-8",
    )

    from rsconnect.bundle import Manifest

    uv_path = uv.find_uv_bin()
    expected_uv_version = subprocess.check_output([uv_path, "--version"], text=True).split()[1]
    env_dir = project_dir / ".venv"
    subprocess.run([uv_path, "venv", "--python", sys.executable, str(env_dir)], check=True)
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if fallback:
        monkeypatch.setenv("PATH", os.path.dirname(uv_path))
        monkeypatch.setattr(rsconnect.environment.uv, "find_uv_bin", missing_bundled_uv)
    else:
        monkeypatch.setenv("PATH", "")
    env = Environment.create_python_environment(str(project_dir), requirements_file="uv.lock", python=str(python))

    assert env.filename == "requirements.txt.lock"
    assert "aiofiles==24.1.0" in env.contents
    assert "annotated-doc==0.0.4" in env.contents
    assert "annotated-types==0.7.0" in env.contents
    assert env.source == "uv_lock"
    assert env.package_manager == "uv"
    assert env.pip is None
    assert Manifest(environment=env).data["python"]["package_manager"]["version"] == expected_uv_version


@pytest.mark.parametrize("default_groups", ["", '[tool.uv]\ndefault-groups = ["dev", "lint"]\n'])
def test_uv_lock_export_excludes_dependency_groups(tmp_path, default_groups):
    packages = {
        "runtime-pkg": [],
        "dev-pkg": ["transitive-pkg"],
        "transitive-pkg": [],
        "lint-pkg": [],
        "other-pkg": [],
    }
    for name, dependencies in packages.items():
        package_dir = tmp_path / name
        package_dir.mkdir()
        (package_dir / "pyproject.toml").write_text(
            f'[project]\nname = "{name}"\nversion = "1.0.0"\ndependencies = {dependencies!r}\n'
            + ('[tool.uv.sources]\ntransitive-pkg = { path = "../transitive-pkg" }\n' if dependencies else ""),
            encoding="utf-8",
        )

    sources = "".join(f'{name} = {{ path = "{name}" }}\n' for name in packages)
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "demo"\nversion = "1.0.0"\n'
        'dependencies = ["runtime-pkg"]\n'
        '[dependency-groups]\ndev = ["dev-pkg"]\nlint = ["lint-pkg"]\nother = ["other-pkg"]\n'
        f"{default_groups}[tool.uv.sources]\n{sources}",
        encoding="utf-8",
    )
    subprocess.run([uv.find_uv_bin(), "lock", "--offline"], cwd=tmp_path, check=True)

    env = Environment.create_python_environment(str(tmp_path), requirements_file="uv.lock", python=sys.executable)

    assert "./runtime-pkg" in env.contents
    for name in ("dev-pkg", "transitive-pkg", "lint-pkg", "other-pkg"):
        assert name not in env.contents


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_pyproject_dependencies(tmp_path, encoding):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text(
        "[project]\n"
        "name = 'demo'\n"
        "version = '0.0.0'\n"
        "dependencies = [\n"
        "    'aiofiles==24.1.0',\n"
        "    'annotated-types>=0.7.0',\n"
        "    'rsconnect-python==1.0.0',\n"
        "]\n",
        encoding=encoding,
    )

    env = detect_environment(str(project_dir), requirements_file="pyproject.toml")

    assert env.filename == "requirements.txt"
    assert "aiofiles==24.1.0" in env.contents
    assert "annotated-types>=0.7.0" in env.contents
    # rsconnect dependency lines must be stripped, matching the behavior of output_file() and pip_freeze()
    dep_lines = [line for line in env.contents.splitlines() if line and not line.startswith("#")]
    assert dep_lines == ["aiofiles==24.1.0", "annotated-types>=0.7.0"]
    assert env.contents.endswith("\n")
    assert env.source == "pyproject_toml"
    assert env.package_manager == "pip"


@pytest.mark.parametrize("encoding", ["utf-8", "utf-8-sig"])
def test_pyproject_dependencies_invalid_toml(tmp_path, encoding):
    (tmp_path / "pyproject.toml").write_text("[project\ndependencies =", encoding=encoding)

    with pytest.raises(EnvironmentException, match="Error reading pyproject.toml"):
        detect_environment(str(tmp_path), requirements_file="pyproject.toml")


@pytest.mark.parametrize(
    "dependencies",
    [
        "3",
        "[3]",
        "[{a = 'b'}]",
        pytest.param(
            "['flask', 3]",
            marks=pytest.mark.skipif(sys.version_info < (3, 11), reason="toml fallback rejects heterogeneous arrays"),
        ),
        pytest.param(
            "['flask', {a = 'b'}]",
            marks=pytest.mark.skipif(sys.version_info < (3, 11), reason="toml fallback rejects heterogeneous arrays"),
        ),
        "[true]",
        "[['flask']]",
    ],
)
def test_pyproject_dependencies_invalid(tmp_path, dependencies):
    (tmp_path / "pyproject.toml").write_text(f"[project]\ndependencies = {dependencies}\n", encoding="utf-8")

    with pytest.raises(
        EnvironmentException, match=r"Invalid project\.dependencies in pyproject\.toml: expected a list of strings\."
    ):
        detect_environment(str(tmp_path), requirements_file="pyproject.toml")


@pytest.mark.parametrize("dependencies", ["[]", "['rsconnect-python']"])
def test_pyproject_dependencies_empty(tmp_path, dependencies):
    (tmp_path / "pyproject.toml").write_text(f"[project]\ndependencies = {dependencies}\n", encoding="utf-8")

    env = detect_environment(str(tmp_path), requirements_file="pyproject.toml")

    assert len(env.contents.splitlines()) == 1
    assert env.contents.endswith("\n")


def test_requirements_file_keeps_crlf_line_endings(tmp_path: Path):
    (tmp_path / "requirements.txt").write_bytes(b"numpy\r\npandas\r\n")

    env = Environment.create_python_environment(str(tmp_path))

    assert env.contents == "numpy\r\npandas\r\n"


def test_pyproject_dependencies_missing(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()

    with pytest.raises(EnvironmentException, match="pyproject.toml not found"):
        detect_environment(str(project_dir), requirements_file="pyproject.toml")


def test_pyproject_dependencies_no_project_table(tmp_path):
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    (project_dir / "pyproject.toml").write_text("[build-system]\nrequires = ['setuptools']\n", encoding="utf-8")

    env = detect_environment(str(project_dir), requirements_file="pyproject.toml")

    assert env.filename == "requirements.txt"
    assert env.source == "pyproject_toml"
    # Header comment is present but no dependencies are listed.
    assert all(line.startswith("#") or line == "" for line in env.contents.splitlines())


class WhichPythonTestCase(TestCase):
    def setUp(self):
        # which_python() falls back to sys.executable only without an active or project environment.
        environ = {name: value for name, value in os.environ.items() if name not in ("VIRTUAL_ENV", "CONDA_PREFIX")}
        patcher = mock.patch.dict(os.environ, environ, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        workdir = tempfile.TemporaryDirectory()
        self.addCleanup(workdir.cleanup)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(workdir.name)

    def test_default(self):
        self.assertEqual(which_python(), sys.executable)

    def test_none(self):
        self.assertEqual(which_python(None), sys.executable)

    def test_sys(self):
        self.assertEqual(which_python(sys.executable), sys.executable)

    def test_does_not_exist(self):
        with tempfile.NamedTemporaryFile() as tmpfile:
            name = tmpfile.name
        with self.assertRaises(RSConnectException):
            which_python(name)

    def test_is_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(RSConnectException):
                which_python(tmpdir)

    @pytest.mark.skipif(sys.platform.startswith("win"), reason="os.X_OK always returns True")
    def test_is_not_executable(self):
        with tempfile.NamedTemporaryFile() as tmpfile:
            with self.assertRaises(RSConnectException):
                which_python(tmpfile.name)


def test_python_environment_lookup_order(tmp_path, monkeypatch):
    for name in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        monkeypatch.delenv(name, raising=False)

    def make_interpreter(environment, conda=False):
        executable = (
            "python.exe" if os.name == "nt" and conda else "Scripts/python.exe" if os.name == "nt" else "bin/python"
        )
        path = environment / executable
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        path.chmod(0o755)
        return str(path)

    project = tmp_path / "project"
    nested = project / "content" / "nested"
    nested.mkdir(parents=True)
    activated = make_interpreter(tmp_path / "active")
    parent = make_interpreter(project / ".venv")
    nearest = make_interpreter(project / "content" / ".venv")
    conda = make_interpreter(tmp_path / "conda", conda=True)

    assert which_python(directory=str(nested)) == nearest
    assert which_python(directory=str(project)) == parent
    monkeypatch.setenv("CONDA_PREFIX", str(tmp_path / "conda"))
    assert which_python(directory=str(nested)) == conda
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "active"))
    assert which_python(directory=str(nested)) == activated
    assert which_python(sys.executable, directory=str(nested)) == sys.executable
    monkeypatch.delenv("VIRTUAL_ENV")
    monkeypatch.delenv("CONDA_PREFIX")
    assert which_python(directory=str(nested)) == nearest


@pytest.mark.skipif(os.name == "nt", reason="uses the POSIX environment layout")
def test_conda_environment_ranks_by_kind_like_uv(tmp_path, monkeypatch):
    for name in ("VIRTUAL_ENV", "CONDA_PREFIX", "_CONDA_ROOT", "CONDA_DEFAULT_ENV"):
        monkeypatch.delenv(name, raising=False)

    def make_interpreter(environment):
        path = environment / "bin/python"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        path.chmod(0o755)
        return str(path)

    project = tmp_path / "project"
    project.mkdir()
    venv = make_interpreter(project / ".venv")
    prefix = tmp_path / "envs" / "analysis"
    conda = make_interpreter(prefix)
    monkeypatch.setenv("CONDA_PREFIX", str(prefix))

    # No CONDA_DEFAULT_ENV, so the prefix is treated as a path-based (non-base) environment.
    assert which_python(directory=str(project)) == conda

    monkeypatch.setenv("CONDA_DEFAULT_ENV", "analysis")
    assert which_python(directory=str(project)) == conda

    # A base environment ranks below the project environment.
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
    assert which_python(directory=str(project)) == venv

    monkeypatch.setenv("_CONDA_ROOT", str(prefix))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "analysis")
    assert which_python(directory=str(project)) == venv

    # Without a project environment, the base environment is still used.
    (project / ".venv" / "bin" / "python").unlink()
    assert which_python(directory=str(project)) == conda


def test_project_environment_lookup_ignores_non_ancestors(tmp_path, monkeypatch):
    for name in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        monkeypatch.delenv(name, raising=False)
    current = tmp_path / "current"
    (tmp_path / "sibling").mkdir()
    python = current / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_text("")
    python.chmod(0o755)
    monkeypatch.chdir(current)

    assert which_python(directory=os.path.join("..", "sibling")) == sys.executable


def test_project_environment_lookup_includes_ancestors_outside_content_project(tmp_path, monkeypatch):
    for name in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        monkeypatch.delenv(name, raising=False)
    content = tmp_path / "project" / "content"
    content.mkdir(parents=True)
    (tmp_path / "project" / "pyproject.toml").write_text("[project]\nname = 'example'\n")
    python = tmp_path / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    python.parent.mkdir(parents=True)
    python.write_text("")
    python.chmod(0o755)

    assert which_python(directory=str(content)) == str(python)


def test_inspect_environment_without_bundled_uv(monkeypatch):
    monkeypatch.setattr(rsconnect.environment.uv, "find_uv_bin", missing_bundled_uv)
    environment = Environment._inspect_environment(sys.executable, get_dir("pip1"))
    assert environment.source == "file"


def test_inspect_environment_reports_invalid_pyproject(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project\n")
    with pytest.raises(RSConnectException, match="Error reading pyproject.toml"):
        Environment._inspect_environment(sys.executable, str(tmp_path), requirements_file="pyproject.toml")


@pytest.mark.parametrize("output", [b"banner\n", b""])
def test_inspection_json_errors_name_interpreter(tmp_path, output):
    with pytest.raises(RSConnectException, match="Error parsing environment JSON from Python /selected/python"):
        Environment._inspect_environment("/selected/python", str(tmp_path), check_output=lambda *args, **kwargs: output)


def test_inspection_subprocess_errors_name_interpreter(tmp_path):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args[0])

    with pytest.raises(RSConnectException, match="Error inspecting environment with Python /selected/python"):
        Environment._inspect_environment("/selected/python", str(tmp_path), check_output=fail)


def test_isolated_uv_environment_inspection_without_pip_or_rsconnect(tmp_path, monkeypatch, caplog):
    from rsconnect.bundle import Manifest

    for name in ("VIRTUAL_ENV", "CONDA_PREFIX"):
        monkeypatch.delenv(name, raising=False)
    project = tmp_path / "project"
    project.mkdir()
    environment_dir = project / ".venv"
    subprocess.run([uv.find_uv_bin(), "venv", "--python", sys.executable, str(environment_dir)], check=True)
    python = environment_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    wheel = tmp_path / "example_project_dependency-1.2.3-py3-none-any.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr("example_project_dependency.py", "")
        archive.writestr(
            "example_project_dependency-1.2.3.dist-info/METADATA",
            "Metadata-Version: 2.1\nName: example-project-dependency\nVersion: 1.2.3\n",
        )
        archive.writestr(
            "example_project_dependency-1.2.3.dist-info/WHEEL",
            "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
        )
        archive.writestr("example_project_dependency-1.2.3.dist-info/RECORD", "")
    subprocess.run(
        [
            uv.find_uv_bin(),
            "pip",
            "install",
            "--offline",
            "--no-index",
            "--find-links",
            str(tmp_path),
            "--python",
            str(python),
            "example-project-dependency==1.2.3",
        ],
        check=True,
    )
    foreign_path = tmp_path / "foreign"
    foreign_path.mkdir()
    (foreign_path / "pip.py").write_text("raise RuntimeError('foreign pip must not be imported')\n")
    monkeypatch.setenv("PYTHONPATH", str(foreign_path))
    assert (
        subprocess.run(
            [
                str(python),
                "-I",
                "-c",
                "import importlib.util; assert not any(importlib.util.find_spec(x) for x in ('pip', 'rsconnect'))",
            ],
            capture_output=True,
        ).returncode
        == 0
    )

    monkeypatch.setenv("PATH", "")
    with caplog.at_level("INFO"):
        generated = Environment.create_python_environment(str(project), requirements_file=None)
    assert generated.python_interpreter == str(python)
    assert f"Using Python: {python}" in caplog.text
    assert (
        generated.python
        == subprocess.check_output(
            [str(python), "-I", "-c", "import sys; print('%d.%d.%d' % sys.version_info[:3])"], text=True
        ).strip()
    )
    assert generated.pip is None
    assert "example-project-dependency==1.2.3" in generated.contents
    assert "click==" not in generated.contents
    assert Manifest(environment=generated).data["python"]["package_manager"]["version"] == ""

    (project / "requirements.txt").write_text("project-package==1.0\n")
    monkeypatch.chdir(tmp_path)
    existing = Environment.create_python_environment(str(project), python=os.path.relpath(python))
    assert existing.pip is None
    assert existing.contents.splitlines() == ["project-package==1.0"]
    uv_environment = Environment.create_python_environment(
        str(project), python=str(python), package_manager=PackageInstaller.UV
    )
    expected_uv_version = subprocess.check_output([uv.find_uv_bin(), "--version"], text=True).split()[1]
    assert Manifest(environment=uv_environment).data["python"]["package_manager"]["version"] == expected_uv_version

    (project / "pyproject.toml").write_text('[project]\nname = "demo"\ndependencies = ["other-package>=2"]\n')
    pyproject = Environment.create_python_environment(str(project), requirements_file="pyproject.toml")
    assert "other-package>=2" in pyproject.contents
    assert pyproject.pip is None


def test_inspection_when_rsconnect_is_importable_only_from_pythonpath(tmp_path):
    # Mirrors `pip install --user` and PYTHONPATH installs: the interpreter running the CLI has
    # no packages of its own, so the inspector must inherit the CLI's import path.
    cli_env = tmp_path / "cli-env"
    subprocess.run([uv.find_uv_bin(), "venv", "--python", sys.executable, str(cli_env)], check=True)
    cli_python = cli_env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    project = tmp_path / "project"
    project.mkdir()
    (project / "requirements.txt").write_text("project-package==1.0\n")

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(path for path in sys.path if path)
    result = subprocess.run(
        [
            str(cli_python),
            "-c",
            "import json, sys; from rsconnect.environment import Environment; "
            "e = Environment.create_python_environment(sys.argv[1], python=sys.argv[2]); "
            "print(json.dumps(e.contents))",
            str(project),
            str(cli_python),
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.splitlines()[-1]).splitlines() == ["project-package==1.0"]


@pytest.mark.parametrize("fallback", [False, True])
def test_uv_freeze_filters_distributions_and_rejects_editable_file_urls(tmp_path, monkeypatch, fallback):
    uv_path = uv.find_uv_bin()
    env_dir = tmp_path / "env"
    subprocess.run([uv_path, "venv", "--python", sys.executable, str(env_dir)], check=True)
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    site = Path(
        subprocess.check_output(
            [str(python), "-I", "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
        ).strip()
    )
    for name in ("rsconnect-python", "rsconnect-utils", "pip", "setuptools", "wheel", "distribute"):
        dist = site / f"{name.replace('-', '_')}-1.0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
    if fallback:
        monkeypatch.setenv("PATH", os.path.dirname(uv_path))
        monkeypatch.setattr(rsconnect.environment.uv, "find_uv_bin", missing_bundled_uv)
    else:
        monkeypatch.setenv("PATH", "")

    environment = Environment._inspect_environment(str(python), str(tmp_path), requirements_file=None)
    assert "rsconnect-utils==1.0" in environment.contents.splitlines()
    assert "rsconnect-python==1.0" not in environment.contents.splitlines()
    assert "pip==1.0" not in environment.contents.splitlines()
    for name in ("setuptools", "wheel", "distribute"):
        assert (f"{name}==1.0" in environment.contents.splitlines()) == (sys.version_info >= (3, 12))

    local = tmp_path / "editable project"
    local.mkdir()
    dist = site / "editable_project-1.0.dist-info"
    dist.mkdir()
    (dist / "METADATA").write_text("Metadata-Version: 2.1\nName: editable-project\nVersion: 1.0\n")
    (dist / "direct_url.json").write_text(json.dumps({"url": local.as_uri(), "dir_info": {"editable": True}}))
    with pytest.raises(RSConnectException, match="Editable dependencies outside the deployment directory"):
        Environment._inspect_environment(str(python), str(tmp_path), requirements_file=None)


def test_filter_uv_editable_rsconnect_file_url():
    line = f"-e {Path(rsconnect_project_dir).as_uri()}"
    assert filter_pip_freeze_output(line) == ""


def test_uv_freeze_does_not_create_relative_cache_in_inspector_directory(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    env_dir = project / ".venv"
    subprocess.run([uv.find_uv_bin(), "venv", "--python", sys.executable, str(env_dir)], check=True)
    python = env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    inspector_dir = tmp_path / "inspector"
    inspector_dir.mkdir()
    inspector = inspector_dir / "inspect_environment.py"
    shutil.copyfile(rsconnect.environment.inspect_environment.__file__, inspector)
    monkeypatch.setattr(rsconnect.environment.inspect_environment, "__file__", str(inspector))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UV_CACHE_DIR", ".cache/uv")

    result = Environment.create_python_environment(str(project), requirements_file=None, python=str(python))

    assert result.source == "pip_freeze"
    assert not (inspector_dir / ".cache").exists()


@pytest.mark.skipif(os.name != "posix", reason="Requires a POSIX user site directory")
def test_isolated_inspection_finds_pip_in_user_site(tmp_path, monkeypatch):
    project = tmp_path / "project"
    project.mkdir()
    env_dir = tmp_path / "environment"
    subprocess.run(
        [uv.find_uv_bin(), "venv", "--system-site-packages", "--python", sys.executable, str(env_dir)], check=True
    )
    python = env_dir / "bin/python"
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("PYTHONUSERBASE", raising=False)
    user_site = Path(
        subprocess.check_output(
            [str(python), "-E", "-c", "import site; print(site.getusersitepackages())"], text=True
        ).strip()
    )
    pip = user_site / "pip"
    pip.mkdir(parents=True)
    (pip / "__init__.py").write_text("")
    (pip / "__main__.py").write_text(
        "import sys\nprint('pip 50.0' if '--version' in sys.argv else 'user-project-dependency==1.2.3')\n"
    )

    result = Environment.create_python_environment(str(project), requirements_file=None, python=str(python))

    assert result.pip == "50.0"
    assert "user-project-dependency==1.2.3" in result.contents


class TestPythonVersionRequirements:
    def test_malformed_pyproject(self, tmp_path):
        (tmp_path / "pyproject.toml").write_text('[project\nname = "x"\n')
        (tmp_path / "requirements.txt").write_text("flask\n")

        with pytest.raises(RSConnectException, match="Error reading pyproject.toml:") as exc_info:
            Environment.create_python_environment(str(tmp_path))

        assert isinstance(exc_info.value.__cause__, rsconnect.environment.pyproject.TOMLDecodeError)
        assert str(exc_info.value.__cause__) in str(exc_info.value)

    def test_pyproject_toml(self):
        env = Environment.create_python_environment(
            os.path.join(TESTDATA, "python-project", "using_pyproject"), requirements_file=None
        )
        assert env.python_interpreter == sys.executable
        assert env.python_version_requirement == ">=3.8"

    def test_python_version(self):
        env = Environment.create_python_environment(
            os.path.join(TESTDATA, "python-project", "using_pyversion"), requirements_file=None
        )
        assert env.python_interpreter == sys.executable
        assert env.python_version_requirement == ">=3.8,<3.12"

    def test_all_of_them(self):
        env = Environment.create_python_environment(
            os.path.join(TESTDATA, "python-project", "allofthem"), requirements_file=None
        )
        assert env.python_interpreter == sys.executable
        assert env.python_version_requirement == ">=3.8,<3.12"

    def test_missing(self):
        env = Environment.create_python_environment(
            os.path.join(TESTDATA, "python-project", "empty"), requirements_file=None
        )
        assert env.python_interpreter == sys.executable
        assert env.python_version_requirement is None


def test_inspect_environment():
    environment = Environment._inspect_environment(sys.executable, get_dir("pip1"))
    assert environment is not None
    assert environment.python != ""


def test_inspect_environment_catches_type_error():
    with pytest.raises(RSConnectException) as exec_info:
        Environment._inspect_environment(sys.executable, None)  # type: ignore

    assert isinstance(exec_info.value, RSConnectException)
    assert isinstance(exec_info.value.__cause__, TypeError)


@pytest.mark.parametrize(
    (
        "file_name",
        "python",
        "requirements_file",
        "expected_python",
        "expected_environment",
    ),
    [
        pytest.param(
            "path/to/file.py",
            sys.executable,
            "requirements.txt",
            sys.executable,
            Environment.from_dict(
                dict(
                    contents=None,
                    filename="requirements.txt",
                    locale="en_US.UTF-8",
                    package_manager="pip",
                    pip=None,
                    python=None,
                    source="pip_freeze",
                    error=None,
                ),
                python_interpreter=sys.executable,
            ),
            id="basic",
        ),
        pytest.param(
            "another/file.py",
            os.path.basename(sys.executable),
            "requirements.txt",
            sys.executable,
            Environment.from_dict(
                dict(
                    contents=None,
                    filename="requirements.txt",
                    locale="en_US.UTF-8",
                    package_manager="pip",
                    pip=None,
                    python=None,
                    source="pip_freeze",
                    error=None,
                ),
                python_interpreter=sys.executable,
            ),
            id="which_python",
        ),
        pytest.param(
            "will/the/files/never/stop.py",
            "argh.py",
            "requirements.txt",
            "unused",
            Environment.from_dict(
                dict(
                    contents=None,
                    filename=None,
                    locale=None,
                    package_manager=None,
                    pip=None,
                    python=None,
                    source=None,
                    error="Could not even do things",
                )
            ),
            id="exploding",
        ),
    ],
)
def test_get_python_env_info(
    monkeypatch,
    file_name,
    python,
    requirements_file,
    expected_python,
    expected_environment,
):
    def fake_which_python(python, directory):
        return expected_python

    def fake_inspect_environment(
        python,
        directory,
        requirements_file="requirements.txt",
        check_output=subprocess.check_output,
    ):
        return expected_environment

    monkeypatch.setattr(Environment, "_inspect_environment", fake_inspect_environment)

    monkeypatch.setattr(rsconnect.environment, "which_python", fake_which_python)

    if expected_environment.error is not None:
        with pytest.raises(RSConnectException):
            _ = Environment._get_python_env_info(file_name, python, requirements_file=requirements_file)
    else:
        environment = Environment._get_python_env_info(file_name, python, requirements_file=requirements_file)

        assert environment.python_interpreter == expected_python
        assert environment == expected_environment


class TestEnvironmentDeprecations:
    def test_override_python_version(self):
        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1-no-version"), override_python_version=None)
        assert mock_warning.call_count == 0
        assert result.python_version_requirement is None

        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1-no-version"), override_python_version="3.8.1")
        assert mock_warning.call_count == 1
        mock_warning.assert_called_once_with(
            "The --override-python-version option is deprecated, "
            "please use a .python-version file to force a specific interpreter version."
        )
        assert result.python_version_requirement == "==3.8.1"

    def test_minor_python_override(self):
        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1-no-version"), override_python_version="3.8")

        assert result.python == ".".join(str(part) for part in sys.version_info[:3])
        assert result.python_version_requirement == "==3.8.*"
        mock_warning.assert_called_once_with(
            "The --override-python-version option is deprecated, "
            "please use a .python-version file to force a specific interpreter version."
        )

    def test_python_interpreter(self):
        current_python_version = ".".join((str(v) for v in sys.version_info[:3]))

        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1"))
        assert mock_warning.call_count == 0
        assert result.python == current_python_version

        with mock.patch.object(rsconnect.environment.logger, "warning") as mock_warning:
            result = Environment.create_python_environment(get_dir("pip1"), python=sys.executable)
        mock_warning.assert_not_called()
        assert result.python == current_python_version


class TestRequirementsFileRequired:
    """When a requirements file is requested (the default), it must exist.
    When force-generate is used (requirements_file=None), pip freeze is used regardless."""

    def test_requirements_requested_and_file_exists(self):
        """Default behavior with requirements.txt present succeeds and reads the file."""
        result = Environment.create_python_environment(get_dir("pip1"))
        assert result.source == "file"
        assert result.filename == "requirements.txt"

    def test_requirements_requested_and_file_missing(self):
        """Default behavior without requirements.txt raises an error."""
        with pytest.raises(RSConnectException, match="does not exist"):
            Environment.create_python_environment(get_dir("pip2"))

    def test_force_generate_and_file_exists(self):
        """Force-generate ignores the existing requirements.txt and uses pip freeze."""
        result = Environment.create_python_environment(get_dir("pip1"), requirements_file=None)
        assert result.source == "pip_freeze"

    def test_force_generate_and_file_missing(self):
        """Force-generate works even without requirements.txt."""
        result = Environment.create_python_environment(get_dir("pip2"), requirements_file=None)
        assert result.source == "pip_freeze"

    def test_detect_environment_requires_file(self):
        """Subprocess-level: detect_environment errors when the file is missing."""
        with pytest.raises(EnvironmentException, match="was not found"):
            detect_environment(get_dir("pip2"), requirements_file="requirements.txt")

    def test_detect_environment_reads_file(self):
        """Subprocess-level: detect_environment reads the file when present."""
        result = detect_environment(get_dir("pip1"), requirements_file="requirements.txt")
        assert result.source == "file"

    def test_detect_environment_force_generate(self):
        """Subprocess-level: detect_environment uses pip freeze when requirements_file=None."""
        result = detect_environment(get_dir("pip2"), requirements_file=None)
        assert result.source == "pip_freeze"
