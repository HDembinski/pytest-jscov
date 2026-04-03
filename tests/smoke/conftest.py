import pytest

from pytest_jscov.plugin import JsCovPlugin


# This fixture is used to reset the state of the JsCovPlugin between tests,
# ensuring that coverage data from one test does not affect another.
@pytest.fixture(autouse=True)
def reset_jscov_state(request):
    plugin = request.config.pluginmanager.get_plugin(JsCovPlugin.name)
    if plugin is None:
        yield
        return

    plugin.accumulated.clear()
    plugin.sources.clear()
    yield
