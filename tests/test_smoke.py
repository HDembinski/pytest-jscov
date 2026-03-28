"""Smoke test: run the inner test suite via subprocess with --cov to exercise
the full jscov plugin pipeline end-to-end."""

import re
import subprocess
import sys


def test_smoke():
    """Check that the output of `pytest --cov` includes app.js."""
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
    assert m and int(m.group(1)) > 0 and int(m.group(2)) < int(m.group(1))


def test_jscov_cli_overrides_config():
    """--jscov should override static_root from pyproject.toml.

    pyproject.toml sets static_root = "tests/data/static", which resolves
    app.js correctly. Passing --jscov with a wrong path should prevent app.js
    from appearing in the coverage report.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/smoke",
            "--cov",
            "--jscov=nonexistent/path",
            "-x",
            "-v",
        ],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 0, f"pytest failed (rc={result.returncode}):\n{output}"
    # app.js must NOT appear in the coverage report — the CLI override pointed
    # to a bogus path, so the plugin couldn't map the JS coverage to real files.
    assert not re.search(r"app\.js", output)
