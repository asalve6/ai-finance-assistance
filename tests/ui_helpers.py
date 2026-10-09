"""Helpers for driving the real Streamlit app headlessly in tests."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from penny.graph.build import PennyGraph
from penny.observability import InMemoryTraceSink
from penny.ui.backend import Backend

APP = str(Path(__file__).resolve().parents[1] / "src" / "penny" / "ui" / "app.py")


def offline_backend() -> Backend:
    sink = InMemoryTraceSink()
    return Backend(PennyGraph(sink=sink), sink, False, "TEST_KEY is not set in .env")


def launch(**session) -> AppTest:
    """Start the app. Unless a test passes its own, the backend is the offline one, so no test
    can reach a real provider through keys in the developer's shell."""
    session.setdefault("backend", offline_backend())
    app = AppTest.from_file(APP, default_timeout=30)
    for key, value in session.items():
        app.session_state[key] = value
    app.run()
    assert not app.exception, app.exception
    return app


def button(app: AppTest, label: str):
    matches = [b for b in app.button if b.label == label]
    assert matches, f"no button labelled {label!r}; have {[b.label for b in app.button]}"
    return matches[0]


def click(app: AppTest, label: str) -> AppTest:
    button(app, label).click().run()
    assert not app.exception, app.exception
    return app


def has_button(app: AppTest, label: str) -> bool:
    return any(b.label == label for b in app.button)
