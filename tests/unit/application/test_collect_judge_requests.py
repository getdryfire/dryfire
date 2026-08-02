"""DF-303 — collecting judge requests from a case's expect entries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from dryfire.application.judging.collect import collect_judge_requests
from dryfire.domain.judging.keys import judge_key
from dryfire.domain.judging.rubric import Rubric
from dryfire.domain.model.case import ResolvedCase


def _case(expect: list[dict[str, Any]], *, model: str = "claude-opus-4-8") -> ResolvedCase:
    return ResolvedCase(
        suite_name="s", case_name="c", suite_path=Path("s.eval.yaml"),
        provider="anthropic", model=model, max_turns=4, temperature=0.0,
        on_unmocked="error", system=None, input="hi", expect=expect,
    )


def test_structural_only_case_yields_no_requests() -> None:
    case = _case([{"calls_tool": "lookup"}, {"final_contains": "done"}])
    assert collect_judge_requests(case) == []


def test_collects_one_request_per_distinct_judge() -> None:
    case = _case([
        {"calls_tool": "lookup"},
        {"llm_judge": {"rubric": "Was it polite?"}},
        {"llm_judge": {"rubric": "Was it correct?"}},
    ])
    requests = collect_judge_requests(case)
    assert len(requests) == 2
    assert {r.rubric.text for r in requests} == {"Was it polite?", "Was it correct?"}


def test_identical_judges_dedupe_to_one_request() -> None:
    case = _case([
        {"llm_judge": {"rubric": "Was it polite?", "threshold": 0.7}},
        {"llm_judge": {"rubric": "Was it polite?", "threshold": 0.7}},
    ])
    assert len(collect_judge_requests(case)) == 1


def test_model_defaults_to_the_case_model_and_keys_by_it() -> None:
    case = _case([{"llm_judge": {"rubric": "Was it polite?"}}], model="claude-opus-4-8")
    request = collect_judge_requests(case)[0]
    assert request.model == "claude-opus-4-8"
    assert request.assertion_id == judge_key(
        model="claude-opus-4-8", rubric_hash=Rubric(text="Was it polite?").hash()
    )


def test_model_override_is_used_and_changes_the_key() -> None:
    case = _case([{"llm_judge": {"rubric": "Was it polite?", "model": "claude-haiku-4-5"}}])
    request = collect_judge_requests(case)[0]
    assert request.model == "claude-haiku-4-5"
    assert request.assertion_id == judge_key(
        model="claude-haiku-4-5", rubric_hash=Rubric(text="Was it polite?").hash()
    )
