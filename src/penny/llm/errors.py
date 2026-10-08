"""One error type for every LLM provider, so agents never import a provider's exceptions."""

from __future__ import annotations


class LLMError(RuntimeError):
    """A model call failed. `retryable` is True for rate limits, timeouts, 5xx and network errors.

    The provider SDKs already retry a couple of times, so by the time this is raised a retry is
    the caller's decision (for example fall back to a templated answer).
    """

    def __init__(
        self, message: str, *, retryable: bool = False, status_code: int | None = None
    ) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status_code = status_code


def status_is_retryable(status_code: int) -> bool:
    return status_code in (408, 409, 429) or status_code >= 500
