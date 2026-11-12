"""Opt-in integration checks against an isolated Python with pip installed."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import uv
from rsconnect.environment import Environment


@pytest.mark.skipif(not os.environ.get("RSCONNECT_COMPAT_PYTHON"), reason="No compatibility interpreter selected")
def test_dependency_inspection_with_selected_pip(tmp_path: Path):
    base_python = os.path.abspath(os.environ["RSCONNECT_COMPAT_PYTHON"])
    repo = Path(__file__).resolve().parents[1]
    env_dir = tmp_path / "env"
    subprocess.run([base_python, "-m", "venv", "--without-pip", str(env_dir)], check=True)
    python = str(env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    site = Path(
        subprocess.check_output(
            [python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
        ).strip()
    )
    base_site = Path(
        subprocess.check_output(
            [base_python, "-c", "import os,pip; print(os.path.dirname(os.path.dirname(pip.__file__)))"], text=True
        ).strip()
    )
    shutil.copytree(base_site / "pip", site / "pip")
    for metadata in base_site.glob("pip-*.dist-info"):
        shutil.copytree(metadata, site / metadata.name)
    for name in ("rsconnect", "rsconnect-python", "rsconnect-utils", "demo-url", "setuptools", "wheel", "distribute"):
        dist = site / f"{name.replace('-', '_')}-1.0.dist-info"
        dist.mkdir()
        (dist / "METADATA").write_text(f"Metadata-Version: 2.1\nName: {name}\nVersion: 1.0\n")
        if name == "demo-url":
            (dist / "direct_url.json").write_text(
                json.dumps({"url": "https://example.com/rsconnect/demo.whl", "archive_info": {}})
            )

    env = os.environ.copy()
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"

    def inspect(requirements_file):
        result = subprocess.run(
            [
                sys.executable,
                str(repo / "rsconnect/subprocesses/inspect_environment.py"),
                "--python",
                python,
                "--uv",
                uv.find_uv_bin(),
                "-r",
                requirements_file,
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            cwd=tmp_path,
            env=env,
        )
        return json.loads(result.stdout)

    generated = inspect("none")
    assert generated["pip"] == subprocess.check_output([python, "-m", "pip", "--version"], text=True).split()[1]
    lines = generated["contents"].splitlines()
    assert "rsconnect-utils==1.0" in lines
    assert "demo-url @ https://example.com/rsconnect/demo.whl" in lines
    assert "rsconnect==1.0" not in lines
    assert "rsconnect-python==1.0" not in lines
    pip_lines = subprocess.check_output([python, "-m", "pip", "freeze"], text=True, env=env).splitlines()
    for name in ("pip", "setuptools", "wheel", "distribute"):
        assert any(line.startswith(f"{name}==") for line in lines) == any(
            line.startswith(f"{name}==") for line in pip_lines
        )

    local = tmp_path / "rsconnect-local"
    local.mkdir()
    metadata = site / "demo_local-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text("Metadata-Version: 2.1\nName: demo-local\nVersion: 1.0\n")
    (metadata / "direct_url.json").write_text(json.dumps({"url": local.as_uri(), "dir_info": {"editable": True}}))
    generated = inspect("none")
    assert "-e ./rsconnect-local" in generated["contents"].splitlines()

    (tmp_path / "requirements.txt").write_text(
        "rsconnect==1.0\nrsconnect-python==1.0\nrsconnect-utils==1.0\n"
        "demo-url @ https://example.com/rsconnect/demo.whl\n-e ./rsconnect-local\n"
    )
    requirements = inspect("requirements.txt")
    assert requirements["contents"] == (
        "rsconnect-utils==1.0\ndemo-url @ https://example.com/rsconnect/demo.whl\n-e ./rsconnect-local\n"
    )


@pytest.mark.skipif(not os.environ.get("RSCONNECT_COMPAT_PYTHON"), reason="No compatibility interpreter selected")
@pytest.mark.parametrize("installer", ["pip", "uv"])
def test_rewritten_editable_with_spaces_installs(tmp_path: Path, installer: str):
    base_python = os.path.abspath(os.environ["RSCONNECT_COMPAT_PYTHON"])
    project = tmp_path / "project"
    package = project / "local package"
    package.mkdir(parents=True)
    (package / "setup.py").write_text(
        "from setuptools import setup\nsetup(name='local-package', version='1.0', py_modules=['local_module'])\n"
    )
    (package / "local_module.py").write_text("value = 42\n")
    (project / "requirements.txt").write_text(f"-e {package.as_uri()}\n")
    requirements = Environment.create_python_environment(str(project)).contents
    assert requirements == "-e file:./local%20package\n"

    deployed = tmp_path / "deployed"
    shutil.copytree(project, deployed)
    (deployed / "requirements.txt").write_text(requirements)
    env_dir = tmp_path / "env"
    subprocess.run([base_python, "-m", "venv", "--without-pip", str(env_dir)], check=True)
    python = str(env_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python"))
    site = Path(
        subprocess.check_output(
            [python, "-c", "import sysconfig; print(sysconfig.get_path('purelib'))"], text=True
        ).strip()
    )
    module_paths = json.loads(
        subprocess.check_output(
            [
                base_python,
                "-c",
                "import importlib.util, json; "
                "print(json.dumps({n: (s.origin if (s := importlib.util.find_spec(n)) else None) "
                "for n in ('pip', 'setuptools', 'wheel', '_distutils_hack')}))",
            ],
            text=True,
        )
    )
    if not all(module_paths.values()):
        pytest.skip("Compatibility interpreter needs pip, setuptools, and wheel for editable installation")
    for name in ("pip", "setuptools", "wheel", "_distutils_hack"):
        shutil.copytree(Path(module_paths[name]).parent, site / name)
    for pattern in ("pip-*.dist-info", "setuptools-*.dist-info", "wheel-*.dist-info", "distutils-precedence.pth"):
        for base_site in {Path(path).parent.parent for path in module_paths.values()}:
            for item in base_site.glob(pattern):
                if item.is_dir():
                    shutil.copytree(item, site / item.name, dirs_exist_ok=True)
                else:
                    shutil.copy2(item, site / item.name)

    command = (
        [python, "-m", "pip", "install"]
        if installer == "pip"
        else [uv.find_uv_bin(), "pip", "install", "--python", python]
    )
    subprocess.run(
        command + ["--no-deps", "--no-build-isolation", "-r", "requirements.txt"],
        cwd=deployed,
        check=True,
    )
    result = subprocess.check_output([python, "-c", "import local_module; print(local_module.value)"], text=True)
    assert result.strip() == "42"
