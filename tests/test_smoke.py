"""Smoke test: run the inner test suite via subprocess with --cov to exercise
the full jscov plugin pipeline end-to-end."""

import re
import subprocess
import sys


def test_smoke():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/smoke",
            "--cov",
            "-x",
            "-v",
        ],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"pytest failed (rc={result.returncode}):\n{output}"
    # Check that app.js appears with a non-zero Stmts count.
    m = re.search(r"app\.js\s+(\d+)\s+(\d+)\s+(\d+)%", output)
    assert m and int(m.group(1)) > 0, (
        f"expected app.js with covered statements in output:\n{output}"
    )
