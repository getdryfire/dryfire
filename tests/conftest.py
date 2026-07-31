"""Shared test fixtures."""

from collections.abc import Callable

import pytest

from agentcheck.application.ports.model_gateway import CompletionRequest, ModelParams
from agentcheck.domain.model.message import Message


@pytest.fixture
def make_request() -> Callable[..., CompletionRequest]:
    """Factory for a minimal CompletionRequest to drive a gateway's complete()."""

    def _make(content: str = "hi") -> CompletionRequest:
        return CompletionRequest(
            model="claude-sonnet-4-6",
            system=None,
            messages=[Message(role="user", content=content)],
            tools=[],
            params=ModelParams(),
        )

    return _make
