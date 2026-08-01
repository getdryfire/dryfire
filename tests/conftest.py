"""Shared test fixtures."""

from collections.abc import Callable, Iterator

import pytest

from dryfire.application.ports.model_gateway import CompletionRequest, ModelParams
from dryfire.domain.model.message import Message


@pytest.fixture
def registry_isolation() -> Iterator[None]:
    """Snapshot and restore the assertion registry so tests that register toy
    assertions don't leak kinds into other tests."""
    from dryfire.domain.assertions import base

    saved = dict(base._REGISTRY)
    try:
        yield
    finally:
        base._REGISTRY.clear()
        base._REGISTRY.update(saved)


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
