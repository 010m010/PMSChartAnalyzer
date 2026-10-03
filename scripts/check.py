"""Run the same project checks locally and in CI."""

import argparse
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]


def project_python() -> Path:
    executable = ROOT / ".venv" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    return executable if executable.is_file() else Path(sys.executable)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--tests-only", action="store_true")
    selection.add_argument("--skills-only", action="store_true")
    args = parser.parse_args()

    python = str(project_python())
    commands = []
    if not args.tests_only:
        commands.append([python, "-B", "scripts/verify_agent_skills.py"])
        commands.append([python, "-B", ".agents/skills/ui-ux-pro-max/scripts/validate_data.py"])
    if not args.skills_only:
        commands.append([python, "-B", "-m", "pytest", "-q"])

    for command in commands:
        print("Running: " + " ".join(command[2:]), flush=True)
        result = subprocess.run(command, cwd=ROOT)
        if result.returncode:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
