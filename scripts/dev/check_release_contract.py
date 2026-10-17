"""Compare the release contract with a committed previous contract, offline.

Breaking changes are allowed with a schema bump and per-dataset migration
notes. Prefer the previous stable tag; untagged forks may explicitly select a
Git ref containing earlier snapshots. Never read baseline bytes from the worktree.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from cnequity.domain.contracts import diff_contracts, load_contract


def previous_release(repo: Path, version: str) -> str:
    match = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if match is None:
        raise ValueError(f"unsupported package version: {version}")
    current = tuple(map(int, match.groups()))
    tags = subprocess.check_output(["git", "tag", "--list", "v*"], cwd=repo, text=True).splitlines()
    candidates = []
    for tag in tags:
        parsed = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", tag)
        if parsed and (parts := tuple(map(int, parsed.groups()))) < current:
            candidates.append((parts, tag))
    if not candidates:
        raise ValueError("no previous stable release tag; fetch full release history")
    return max(candidates)[1]


def _previous_snapshot(repo: Path, version: str, sha: str, ref: str) -> str:
    parsed = re.match(r"^(\d+)\.(\d+)\.(\d+)", version)
    if parsed is None:
        raise ValueError(f"unsupported package version: {version}")
    current = tuple(map(int, parsed.groups()))
    paths = subprocess.check_output(
        ["git", "ls-tree", "-r", "--name-only", sha, "--", "contracts"], cwd=repo, text=True
    ).splitlines()
    candidates = []
    for path in paths:
        match = re.fullmatch(r"contracts/v(\d+)\.(\d+)\.(\d+)\.json", path)
        if match and (parts := tuple(map(int, match.groups()))) < current:
            candidates.append((parts, path))
    if not candidates:
        raise ValueError(f"no previous stable contract before {version} in {ref} ({sha})")
    return max(candidates)[1]


def baseline_contract(
    repo: Path, version: str, baseline_ref: str | None = None
) -> tuple[dict, dict]:
    try:
        tag = previous_release(repo, version)
    except ValueError:
        if baseline_ref is None:
            raise
        tag = None
    ref = tag or baseline_ref
    sha = subprocess.check_output(
        ["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"],
        cwd=repo,
        text=True,
    ).strip()
    path = f"contracts/{tag}.json" if tag else _previous_snapshot(repo, version, sha, ref)
    baseline = json.loads(
        subprocess.check_output(["git", "show", f"{sha}:{path}"], cwd=repo, text=True)
    )
    return baseline, {
        "baseline_tag": tag,
        "baseline_ref": ref,
        "baseline_sha": sha,
        "baseline_path": path,
    }


def compatibility_errors(old: dict, new: dict, notes: Path) -> list[str]:
    errors = []
    changed = {item["dataset"] for item in diff_contracts(old, new)["breaking"]}
    for dataset in sorted(changed):
        previous = old["datasets"][dataset]
        current = new["datasets"].get(dataset)
        if current is not None and current["schema_version"] <= previous["schema_version"]:
            errors.append(f"{dataset}: breaking change requires a schema_version increase")
        note = notes / f"{dataset}.md"
        body = note.read_text(encoding="utf-8") if note.is_file() else ""
        for heading in ("## Change", "## Migration", "## Rollback"):
            if heading not in body or not body.split(heading, 1)[1].split("##", 1)[0].strip():
                errors.append(f"{dataset}: {note} needs a nonempty {heading} section")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--baseline-ref",
        help="Fallback committed Git ref when no previous stable release tag exists",
    )
    args = parser.parse_args()
    current_path = args.current if args.current.is_absolute() else args.repo / args.current
    version = current_path.stem.removeprefix("v")
    old, baseline = baseline_contract(args.repo, version, args.baseline_ref)
    new = load_contract(current_path)
    report = dict(diff_contracts(old, new))
    report.update(baseline)
    report["policy_errors"] = compatibility_errors(
        old, new, args.repo / "contracts" / "migrations" / version
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(
        f"{baseline['baseline_tag'] or baseline['baseline_sha']} -> {version}: "
        f"{report['breaking_count']} breaking, "
        f"{report['compatible_count']} compatible changes"
    )
    for error in report["policy_errors"]:
        print(error)
    return int(bool(report["policy_errors"]))


if __name__ == "__main__":
    raise SystemExit(main())
