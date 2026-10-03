import os
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def setup_directory(tmp_path: Path) -> Path:
    script = "setup.bat" if os.name == "nt" else "setup.sh"
    shutil.copy2(ROOT / script, tmp_path / script)
    (tmp_path / "requirements.txt").write_text("", encoding="utf-8")
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(tmp_path / ".venv")],
        check=True,
        capture_output=True,
        text=True,
    )
    return tmp_path


def run_setup(directory: Path, *args: str) -> subprocess.CompletedProcess[str]:
    if os.name == "nt":
        command = ["cmd.exe", "/d", "/c", "setup.bat", *args]
    else:
        command = ["bash", "setup.sh", *args]
    return subprocess.run(command, cwd=directory, capture_output=True, text=True)


def test_setup_does_not_report_success_after_pip_failure(setup_directory: Path) -> None:
    result = run_setup(setup_directory)
    assert result.returncode != 0
    assert "Setup complete" not in result.stdout


def test_setup_rejects_unknown_options(setup_directory: Path) -> None:
    result = run_setup(setup_directory, "--invalid-option")
    assert result.returncode == 2
    assert "Usage:" in result.stdout + result.stderr
