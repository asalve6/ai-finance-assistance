"""Helpers for driving the real Streamlit app headlessly in tests."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

APP = str(Path(__file__).resolve().parents[1] / "src" / "penny" / "ui" / "app.py")


def launch(**session) -> AppTest:
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
