import pytest
from pathlib import Path
from engines.shared.config import settings
from engines.ingestion.database import is_db_reachable
from engines.ingestion.llm import FakeLLM, set_llm_provider


@pytest.fixture(autouse=True)
def ensure_fake_llm_for_tests():
    """Ensure tests run with FakeLLM and no live API calls."""
    fake = FakeLLM()
    set_llm_provider(fake)
    yield fake
    set_llm_provider(None)


def pytest_runtest_setup(item):
    if item.get_closest_marker("db"):
        if not settings.database_url or not is_db_reachable():
            pytest.skip("Skipping database test: PostgreSQL is not reachable or DATABASE_URL is unset")

