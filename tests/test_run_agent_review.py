from __future__ import annotations

import subprocess
import sys


def test_run_agent_review_help() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/run_agent_review.py", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "计划式 Agent" in result.stdout
    assert "start" in result.stdout
    assert "resume" in result.stdout
