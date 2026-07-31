"""AC-002 — the ModelGateway driven port (ARCHITECTURE §5.1).

The port carries no loop, retry, or assertion logic — only the completion
contract. cost() is deliberately absent; pricing is a separate port (AC-017).
"""

from agentcheck.application.ports.model_gateway import (
    CompletionRequest,
    ModelGateway,
    ModelParams,
)
from agentcheck.domain.model.message import Message, ModelResponse, Usage


class FakeGateway:
    """A stub implementing only the port surface — proves the protocol is
    satisfiable without any provider SDK."""

    name = "fake"

    async def complete(self, request: CompletionRequest) -> ModelResponse:
        return ModelResponse(
            text="ok",
            tool_calls=[],
            stop_reason="end_turn",
            usage=Usage(input_tokens=0, output_tokens=0),
            latency_ms=0,
            raw={},
        )


def _accepts(gateway: ModelGateway) -> ModelGateway:
    # Structural-typing site: mypy --strict rejects a non-conforming argument here.
    return gateway


def test_model_params_have_neutral_defaults() -> None:
    p = ModelParams()
    assert p.temperature is None
    assert p.top_p is None
    assert p.max_tokens is None
    assert p.stop_sequences == []


def test_completion_request_bundles_the_call_inputs() -> None:
    req = CompletionRequest(
        model="claude-sonnet-4-6",
        system="be terse",
        messages=[Message(role="user", content="hi")],
        tools=[],
        params=ModelParams(temperature=0.0),
    )
    assert req.model == "claude-sonnet-4-6"
    assert req.system == "be terse"
    assert req.params.temperature == 0.0


async def test_stub_satisfies_the_gateway_protocol() -> None:
    fake = FakeGateway()
    assert isinstance(fake, ModelGateway)
    _accepts(fake)
    resp = await fake.complete(
        CompletionRequest(
            model="m",
            system=None,
            messages=[Message(role="user", content="hi")],
            tools=[],
            params=ModelParams(),
        )
    )
    assert resp.text == "ok"
