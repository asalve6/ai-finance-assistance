"""Small text helpers for showing values in Streamlit."""

from __future__ import annotations

from penny.money import dollars

__all__ = ["dollars", "md", "weeks"]


def md(text: str) -> str:
    """Make text safe to show with st.markdown / st.write.

    Streamlit treats `$...$` as LaTeX maths, so "save $7.50 of your $60.00" would be mangled.
    Escaping the dollar signs keeps money looking like money.
    """
    return text.replace("$", "\\$")


def weeks(count: int) -> str:
    return f"{count} week" if count == 1 else f"{count} weeks"
