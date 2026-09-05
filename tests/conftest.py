import pytest


@pytest.fixture(autouse=True)
def environment_urls(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ABXLAB_URL", "http://market")
    monkeypatch.setenv("WIKIPEDIA_URL", "https://en.wikipedia.org")
    monkeypatch.setenv("OSWORLD_ENDPOINT", "http://desktop:5000")
