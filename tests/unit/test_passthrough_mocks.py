"""DF-211 — passthrough mocks end to end (SPEC §4.4).

Cross-cutting behavior: the loop hands a `Passthrough` marker to the injected
`ToolInvoker`, a raising impl is an error result the run survives, and a passthrough
case is excluded from cassette recording. Layer-local tests live next to each layer
(`test_passthrough_marker.py`, `test_passthrough_invoker.py`).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from dryfire.adapters.driven.mocking.passthrough import PassthroughInvoker
from dryfire.adapters.driven.providers.fake import FakeGateway, text, tool_call
from dryfire.adapters.driven.spec.loader import load_suite
from dryfire.adapters.driven.spec.mocks import map_mock_rule
from dryfire.adapters.driven.spec.models import MockRule as SpecRule
from dryfire.application.loop import run_case
from dryfire.application.scheduler import PlannedCase, PlannedSuite, run_suites
from dryfire.domain.mocking.resolver import MockResolver, MockRule, Passthrough
from dryfire.domain.model.case import ResolvedCase


def _rc(**over: Any) -> ResolvedCase:
    base: dict[str, Any] = dict(
        suite_name="s", case_name="c", suite_path=Path("s.eval.yaml"), provider="fake",
        model="m", max_turns=10, temperature=0.0, on_unmocked="error", system=None,
        input="go", expect=[], tools=[],
    )
    base.update(over)
    return ResolvedCase(**base)


def _invoker(func: Callable[[dict[str, Any]], Any]) -> PassthroughInvoker:
    return PassthroughInvoker(resolve=lambda _target: func)


async def test_passthrough_result_comes_from_the_invoked_callable() -> None:
    gw = FakeGateway.script([tool_call("create_ticket", {"title": "bug"}), text("Done.")])
    resolver = MockResolver({"create_ticket": [MockRule(outcome=Passthrough(target="t:make"))]})
    invoker = _invoker(lambda a: {"id": 7, "title": a["title"]})

    trace = await run_case(_rc(), gw, resolver, invoker=invoker)

    assert trace.tool_names() == ["create_ticket"]
    assert trace.turns[0].tool_results[0].content == {"id": 7, "title": "bug"}
    assert trace.termination == "end_turn"


async def test_passthrough_raise_is_an_error_result_and_the_run_continues() -> None:
    gw = FakeGateway.script([tool_call("create_ticket", {}), text("Recovered.")])
    resolver = MockResolver({"create_ticket": [MockRule(outcome=Passthrough(target="t:boom"))]})

    def boom(a: dict[str, Any]) -> str:
        raise RuntimeError("api down")

    trace = await run_case(_rc(), gw, resolver, invoker=_invoker(boom))

    result = trace.turns[0].tool_results[0]
    assert result.is_error is True
    assert isinstance(result.content, str) and "api down" in result.content
    assert trace.termination == "end_turn"  # the loop kept going
    assert trace.final_text == "Recovered."


async def test_passthrough_without_an_invoker_is_a_clear_programming_error() -> None:
    gw = FakeGateway.script([tool_call("create_ticket", {}), text("Done.")])
    resolver = MockResolver({"create_ticket": [MockRule(outcome=Passthrough(target="t:make"))]})
    with pytest.raises(RuntimeError, match="passthrough.*ToolInvoker"):
        await run_case(_rc(), gw, resolver)  # no invoker wired


# -- YAML surface: `impl:` is a fourth mock-rule outcome ----------------------


def test_spec_rule_accepts_impl_as_the_single_outcome() -> None:
    rule = SpecRule(impl="mytools.impls:create_ticket")
    assert rule.impl == "mytools.impls:create_ticket"
    assert "impl" in rule.model_fields_set


def test_spec_rule_rejects_impl_combined_with_return() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        SpecRule.model_validate({"impl": "m:f", "return": "x"})


def test_impl_rule_maps_to_a_passthrough_outcome() -> None:
    domain = map_mock_rule(SpecRule(when={"priority": "high"}, impl="m:f"))
    assert domain.when == {"priority": "high"}
    assert domain.outcome == Passthrough(target="m:f")


# -- validate-time resolution: a bad impl: is a positioned spec error ---------


def _suite(tmp_path: Path, impl: str) -> Path:
    path = tmp_path / "s.eval.yaml"
    path.write_text(
        "name: s\n"
        "cases:\n"
        "  - name: c\n"
        "    input: go\n"
        "    mocks:\n"
        "      create_ticket:\n"
        f"        - impl: {impl}\n"
        "    expect:\n"
        "      - calls_tool: create_ticket\n",
        encoding="utf-8",
    )
    return path


def test_bad_impl_is_a_positioned_spec_error(tmp_path: Path) -> None:
    suite, errors = load_suite(_suite(tmp_path, "nonexistent_module_xyz:make"))
    assert suite is None
    assert len(errors) == 1
    err = errors[0]
    assert "impl" in err.message and "nonexistent_module_xyz" in err.message
    assert err.position is not None and err.position.line == 7  # the `impl:` line


def test_resolvable_impl_passes_validation(tmp_path: Path) -> None:
    suite, errors = load_suite(_suite(tmp_path, "json:dumps"))
    assert errors == [] and suite is not None


# -- the scheduler wires the invoker down to each case ------------------------


async def test_run_suites_wires_the_invoker_to_passthrough_cases() -> None:
    gw = FakeGateway.script([tool_call("create_ticket", {"title": "x"}), text("Done.")])
    planned = PlannedCase(
        case=_rc(), gateway=gw,
        mocks={"create_ticket": [MockRule(outcome=Passthrough(target="t:make"))]},
    )
    suite = PlannedSuite(name="s", path=Path("s.eval.yaml"), cases=[planned])

    run = await run_suites([suite], None, invoker=_invoker(lambda a: {"id": 1, **a}))

    result = run.suites[0].cases[0]
    assert result.trace is not None
    assert result.trace.turns[0].tool_results[0].content == {"id": 1, "title": "x"}


# -- passthrough cases are excluded from cassette recording (with a note) -----


def test_passthrough_case_is_excluded_from_cassette_recording(tmp_path: Path) -> None:
    import io

    from dryfire.adapters.driven.cache.file_store import FileCassetteStore
    from dryfire.adapters.driven.providers.caching import CachingGateway
    from dryfire.composition import _wrap_cases

    store = FileCassetteStore(tmp_path / "cassettes")
    inner = FakeGateway.script([text("Done.")])
    pass_case = PlannedCase(  # a real-provider case (gateway=None) using passthrough
        case=_rc(case_name="pass_through"),
        mocks={"create_ticket": [MockRule(outcome=Passthrough(target="t:make"))]},
    )
    plain_case = PlannedCase(case=_rc(case_name="plain"),
                             mocks={"x": [MockRule(outcome=Passthrough(target="t:f"))][:0]})
    suite = PlannedSuite(name="s", path=Path("s.eval.yaml"), cases=[pass_case, plain_case])
    out = io.StringIO()

    wrapped = _wrap_cases(
        [suite], inner_for=lambda pc: inner, store=store, mode="record",
        exclude_passthrough=True, out=out,
    )

    got = {c.case.case_name: c for c in wrapped[0].cases}
    # The passthrough case is NOT wrapped in a CachingGateway — nothing is recorded.
    assert not isinstance(got["pass_through"].gateway, CachingGateway)
    # A normal case still gets cached as usual.
    assert isinstance(got["plain"].gateway, CachingGateway)
    # The exclusion is visible, not silent.
    assert "pass_through" in out.getvalue() and "passthrough" in out.getvalue().lower()
