"""Validate the installed skills against the project's source manifest."""

import argparse
import ast
import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit


def relative_links(text: str) -> list[str]:
    prose = re.sub(r"```[^\n]*\n.*?```", "", text, flags=re.DOTALL)
    links = []
    for destination in re.findall(r"\]\(([^\s)]+)(?:\s+[^)]*)?\)", prose):
        if destination.startswith(("#", "/", "~", "$", "<")) or "{" in destination:
            continue
        parsed = urlsplit(destination)
        if parsed.scheme or not parsed.path:
            continue
        path = unquote(parsed.path)
        if path.lower().endswith((".md", ".yaml", ".py")):
            links.append(path)
    return links


def verify(root: Path) -> list[str]:
    skills = root / ".agents/skills"
    manifest = json.loads((root / ".agents/skills-sources.json").read_text(encoding="utf-8-sig"))
    declared = [name for source in manifest["sources"] for name in source["skills"]]
    if not declared or len(declared) != len(set(declared)):
        raise ValueError("The source manifest must declare unique skill names.")
    if any(not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) for name in declared):
        raise ValueError("The source manifest contains an invalid skill name.")

    errors = []
    expected = set(declared)
    actual = {directory.name for directory in skills.iterdir() if directory.is_dir()}
    for name in sorted(expected - actual):
        errors.append(f"Missing skill: {name}")
    for name in sorted(actual - expected):
        errors.append(f"Unregistered skill: {name}; update the source manifest or remove the unintended installation.")

    forbidden_paths = {"CLAUDE.md", ".claude", ".claude-plugin"}
    forbidden_paths.update(manifest.get("forbiddenProjectPaths", []))
    for forbidden in sorted(forbidden_paths):
        if (root / forbidden).exists():
            errors.append(f"Excluded installation path exists: {forbidden}")
    for source in manifest["sources"]:
        license_path = root / source["license"]
        if not license_path.is_file():
            errors.append(f"Missing license: {source['license']}")

    for name in sorted(expected & actual):
        directory = skills / name
        skill_file = directory / "SKILL.md"
        if not skill_file.is_file():
            errors.append(f"Missing manifest: {name}/SKILL.md")
            continue
        text = skill_file.read_text(encoding="utf-8-sig")
        parts = text.split("---", 2)
        if len(parts) != 3 or parts[0].strip():
            errors.append(f"Invalid frontmatter: {name}/SKILL.md")
            continue
        metadata = parts[1]
        skill_name = re.search(r"^name:\s*[\"']?([a-z0-9-]+)[\"']?\s*$", metadata, re.MULTILINE)
        if not skill_name or skill_name.group(1) != name:
            errors.append(f"Skill name differs from its directory: {name}")
        if not re.search(r"^description:\s*\S", metadata, re.MULTILINE):
            errors.append(f"Missing description: {name}")
        if re.search(r"^disable-model-invocation:\s*true\s*$", metadata, re.MULTILINE):
            policy_file = directory / "agents/openai.yaml"
            if not policy_file.is_file() or not re.search(
                r"^\s*allow_implicit_invocation:\s*false\s*$",
                policy_file.read_text(encoding="utf-8-sig"),
                re.MULTILINE,
            ):
                errors.append(f"Missing explicit-invocation policy: {name}")
        for document in directory.rglob("*.md"):
            if document.name == "CLAUDE.md":
                errors.append(f"Unexpected Claude document: {document.relative_to(root)}")
            for link in relative_links(document.read_text(encoding="utf-8-sig")):
                if not (document.parent / link).is_file():
                    errors.append(f"Broken reference: {document.relative_to(root)} -> {link}")
        for script in directory.rglob("*.py"):
            try:
                ast.parse(script.read_text(encoding="utf-8-sig"), filename=str(script))
            except SyntaxError as error:
                errors.append(f"Invalid Python: {script.relative_to(root)}: {error.msg}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    try:
        errors = verify(args.root.resolve())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print(f"Skill verification failed: {error}")
        return 1
    for error in errors:
        print(error)
    if errors:
        return 1
    print("OK: skill manifests, invocation policies, references, Python syntax, and licenses")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
