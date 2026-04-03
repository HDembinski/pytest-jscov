"""Smoke test: run the inner test suite via subprocess with --cov to exercise
the full jscov plugin pipeline end-to-end."""

import re
import subprocess
import sys

from coverage import Coverage


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
    print(output)
    assert result.returncode == 0, f"pytest failed (rc={result.returncode}):\n{output}"
    # Check that app.js appears with a non-zero Stmts count.
    m = re.search(r"app\.js\s+(\d+)\s+(\d+)\s+(\d+)%", output)
    assert m and int(m.group(1)) > 0 and int(m.group(2)) < int(m.group(1))
    assert "CoverageWarning" not in output


def test_plugin_forces_ctrace_core():
    """The coverage plugin should select a core that supports file tracers."""
    cov = Coverage(config_file=False)
    cov.config.plugins = ["pytest_jscov.covplugin"]

    cov._init()

    assert cov.get_option("run:core") == "ctrace"


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
    print(output)
    assert result.returncode == 0, f"pytest failed (rc={result.returncode}):\n{output}"
    # app.js must NOT appear in the coverage report — the CLI override pointed
    # to a bogus path, so the plugin couldn't map the JS coverage to real files.
    assert not re.search(r"app\.js", output)
    assert "CoverageWarning" not in output


def test_cov_can_target_single_js_file():
    """--cov=path/to/file.js should limit the report to that JS file."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/smoke",
            "--cov=tests/data/static/app.js",
            "-x",
            "-v",
        ],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    print(output)
    assert result.returncode == 0, f"pytest failed (rc={result.returncode}):\n{output}"
    assert re.search(r"app\.js\s+(\d+)\s+(\d+)\s+(\d+)%", output)
    assert not re.search(r"unused\.js\s+(\d+)\s+(\d+)\s+(\d+)%", output)
    assert "CoverageWarning" not in output


def test_uncovered_js_file_reports_missed_statements():
    """Uncovered JS files should report missed statements, not zero statements."""
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/smoke",
            "--cov=tests/data/static",
            "-x",
            "-v",
        ],
        capture_output=True,
        text=True,
    )
    output = result.stdout + result.stderr
    print(output)
    assert result.returncode == 0, f"pytest failed (rc={result.returncode}):\n{output}"

    match = re.search(r"unused\.js\s+(\d+)\s+(\d+)\s+(\d+)%", output)
    assert match, f"unused.js missing from coverage output:\n{output}"

    stmts = int(match.group(1))
    missed = int(match.group(2))
    covered_percent = int(match.group(3))

    assert stmts > 0, f"expected unused.js to report statements, got:\n{output}"
    assert missed == stmts, (
        f"expected all statements missed for unused.js, got:\n{output}"
    )
    assert covered_percent == 0, f"expected 0% coverage for unused.js, got:\n{output}"
    assert "CoverageWarning" not in output
