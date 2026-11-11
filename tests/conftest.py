import pytest

from data.seed import build_db


@pytest.fixture(scope="session")
def db_path(tmp_path_factory):
    """A freshly built copy of the eval database, shared by all tests."""
    return build_db(tmp_path_factory.mktemp("db") / "fintech.db")
