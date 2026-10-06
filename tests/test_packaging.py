"""Regression tests for issue #484: pip-installed statewave_agents must import.

Builds the real wheel and imports statewave_agents from it in a subprocess
whose working directory is outside the repository, so the repo checkout's
`core/` on sys.path cannot mask a packaging regression.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_wheel(tmp_path: Path) -> Path:
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", str(REPO_ROOT), "--no-deps", "-w", str(tmp_path)],
        check=True,
        capture_output=True,
    )
    wheels = list(tmp_path.glob("*.whl"))
    assert len(wheels) == 1, f"expected one wheel, got {wheels}"
    return wheels[0]


def test_wheel_contains_core_package(tmp_path):
    wheel = _build_wheel(tmp_path)
    names = zipfile.ZipFile(wheel).namelist()
    assert "statewave_agents/__init__.py" in names
    assert "core/__init__.py" in names
    assert "core/llm.py" in names
    assert "core/statewave_client.py" in names


def test_statewave_agents_imports_from_installed_wheel(tmp_path):
    wheel = _build_wheel(tmp_path)
    extract_dir = tmp_path / "extracted"
    with zipfile.ZipFile(wheel) as zf:
        zf.extractall(extract_dir)

    code = (
        "import sys; sys.path.insert(0, %r); "
        "import statewave_agents, core, core.llm, core.statewave_client; "
        "print(statewave_agents.__file__); print(core.__file__)"
        % str(extract_dir)
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert str(extract_dir) in result.stdout
    # both packages must resolve from the wheel itself, not the repo or an
    # unrelated site-packages install
    assert all(str(extract_dir) in line for line in result.stdout.strip().splitlines())
