import pytest


@pytest.fixture(autouse=True)
def _ignore_the_developers_dotenv(monkeypatch):
    """Tests must pass the same on every machine, with or without a real .env full of keys."""
    monkeypatch.setenv("PENNY_NO_DOTENV", "1")
