import copy
import json
import runpy
import subprocess
from pathlib import Path

import pytest

from cnequity.domain.contracts import export_contract

GATE = runpy.run_path(
    str(Path(__file__).resolve().parents[2] / "scripts/dev/check_release_contract.py")
)


def test_previous_release_excludes_current_and_prerelease_tags(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "--allow-empty",
            "-m",
            "test",
        ],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    for tag in ["v0.9.0", "v0.11.0", "v0.12.0", "v0.13.0rc1"]:
        subprocess.run(["git", "tag", tag], cwd=tmp_path, check=True)
    assert GATE["previous_release"](tmp_path, "0.12.0.dev0") == "v0.11.0"


def test_breaking_changes_need_both_schema_bump_and_migration(tmp_path):
    old = export_contract()
    new = copy.deepcopy(old)
    new["datasets"]["daily_bars"]["unit_contract"] = {"price": "changed"}
    errors = GATE["compatibility_errors"](old, new, tmp_path)
    assert any("schema_version" in error for error in errors)
    assert any("Migration" in error for error in errors)
    new["datasets"]["daily_bars"]["schema_version"] += 1
    (tmp_path / "daily_bars.md").write_text(
        "## Change\nPrice unit changed.\n## Migration\nRescale old prices.\n## Rollback\nRestore previous snapshot.\n"
    )
    assert GATE["compatibility_errors"](old, new, tmp_path) == []


def test_unchanged_contract_does_not_require_migration(tmp_path):
    contract = export_contract()
    assert GATE["compatibility_errors"](contract, contract, tmp_path) == []


def _commit_contracts(repo, versions):
    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    (repo / "contracts").mkdir()
    for version in versions:
        (repo / "contracts" / f"v{version}.json").write_text(json.dumps(export_contract()))
    subprocess.run(["git", "add", "contracts"], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "committed baseline",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
    )
    sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    subprocess.run(["git", "update-ref", "refs/remotes/origin/main", sha], cwd=repo, check=True)
    return sha


def test_untagged_fork_baseline_reads_committed_snapshot_despite_dirty_files(tmp_path):
    sha = _commit_contracts(tmp_path, ["0.9.0", "0.16.0", "0.17.0"])
    (tmp_path / "contracts/v0.16.0.json").write_text('{"forged": true}')
    (tmp_path / "contracts/v0.16.9.json").write_text('{"untracked": true}')
    baseline, evidence = GATE["baseline_contract"](tmp_path, "0.17.0", "origin/main")
    assert baseline == export_contract()
    assert evidence == {
        "baseline_tag": None,
        "baseline_ref": "origin/main",
        "baseline_sha": sha,
        "baseline_path": "contracts/v0.16.0.json",
    }


def test_untagged_fork_without_an_older_committed_snapshot_fails_clearly(tmp_path):
    _commit_contracts(tmp_path, ["0.17.0"])
    with pytest.raises(ValueError, match="no previous stable contract.*origin/main"):
        GATE["baseline_contract"](tmp_path, "0.17.0", "origin/main")


def test_release_tag_baseline_takes_precedence_over_optional_fork_ref(tmp_path):
    sha = _commit_contracts(tmp_path, ["0.16.0"])
    subprocess.run(["git", "tag", "v0.16.0"], cwd=tmp_path, check=True)
    (tmp_path / "contracts/v0.16.0.json").write_text('{"forged": true}')
    baseline, evidence = GATE["baseline_contract"](tmp_path, "0.17.0", "nonexistent")
    assert baseline == export_contract()
    assert evidence["baseline_tag"] == "v0.16.0"
    assert evidence["baseline_sha"] == sha
    assert evidence["baseline_path"] == "contracts/v0.16.0.json"
