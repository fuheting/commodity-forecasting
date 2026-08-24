from __future__ import annotations

import subprocess
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ACCEPTED_ARTIFACT_PATHS = ("data", "docs/findings")


def test_tracked_accepted_artifacts_match_the_git_index() -> None:
    result = subprocess.run(
        [
            "git",
            "diff",
            "--no-ext-diff",
            "--name-only",
            "--diff-filter=ACDMRTUXB",
            "--",
            *ACCEPTED_ARTIFACT_PATHS,
        ],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        check=True,
        text=True,
    )

    changed_paths = [path for path in result.stdout.splitlines() if path]
    assert changed_paths == [], "\n".join(changed_paths)
