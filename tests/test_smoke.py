"""Smoke test: run the inner test suite via subprocess with --cov to exercise
the full jscov plugin pipeline end-to-end."""

import subprocess
import sys


def test_smoke():
    result = subprocess.run(
        [
            sys.executable, "-m", "pytest",
            "tests/smoke",
            "--cov", "-x", "-v",
        ],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, (
        f"pytest failed (rc={result.returncode}):\n{output}"
    )
    assert "app.js" in output, (
        f"expected JS coverage for app.js in output:\n{output}"
    )
