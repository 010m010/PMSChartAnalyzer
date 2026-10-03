import json
from pathlib import Path
import subprocess
import sys


VERIFY_SCRIPT = Path(__file__).resolve().parents[1] / "scripts/verify_agent_skills.py"


def skill_project(root: Path, body: str = "# Sample\n") -> Path:
    skill = root / ".agents/skills/sample"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: sample\ndescription: Sample guidance.\n---\n" + body,
        encoding="utf-8",
    )
    (root / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    (root / ".agents/skills-sources.json").write_text(
        json.dumps({"sources": [{"skills": ["sample"], "license": "LICENSE"}]}),
        encoding="utf-8",
    )
    return root


def run_verifier(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-B", str(VERIFY_SCRIPT), "--root", str(root)],
        capture_output=True,
        text=True,
    )


def test_unintended_installer_additions_fail_the_check(tmp_path: Path) -> None:
    project = skill_project(tmp_path)
    (project / ".agents/skills/unwanted-addon").mkdir()
    result = run_verifier(project)
    assert result.returncode == 1
    assert "Unregistered skill: unwanted-addon" in result.stdout


def test_reference_examples_are_ignored_but_broken_references_fail(tmp_path: Path) -> None:
    project = skill_project(tmp_path, "```md\n[Example](missing.md)\n```\n")
    assert run_verifier(project).returncode == 0
    skill_file = project / ".agents/skills/sample/SKILL.md"
    with skill_file.open("a", encoding="utf-8") as document:
        document.write("\n[Required guide](missing.md)\n")
    result = run_verifier(project)
    assert result.returncode == 1
    assert "Broken reference:" in result.stdout


def test_excluded_files_inside_a_registered_skill_fail_the_check(tmp_path: Path) -> None:
    project = skill_project(tmp_path)
    manifest_path = project / ".agents/skills-sources.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["forbiddenProjectPaths"] = [".agents/skills/sample/scripts/tests"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (project / ".agents/skills/sample/scripts/tests").mkdir(parents=True)
    result = run_verifier(project)
    assert result.returncode == 1
    assert "Excluded installation path exists:" in result.stdout
