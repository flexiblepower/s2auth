import pytest
from s2auth.common.dependencies import setup


@pytest.fixture(autouse=True)
def wire_dependencies(request: pytest.FixtureRequest):
    if "skip_wire" in request.keywords:
        yield
        return
    setup()
    yield
