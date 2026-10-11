import pytest


@pytest.fixture(autouse=True)
def no_saved_gemini_key_in_ui_tests(monkeypatch):
    # UI tests must never use the developer's saved account when requesting LLM data.
    monkeypatch.setattr("golyah.bridge.get_key", lambda: "")
