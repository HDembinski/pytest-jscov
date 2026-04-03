"""Pytest plugin for JavaScript coverage via Playwright CDP."""

from pytest_jscov.playwright_patch import save_coverage

__all__ = ["save_coverage"]
