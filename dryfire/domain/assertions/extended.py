"""Extended assertions (SPEC §6.2, DF-208): min_tool_calls, final_matches, final_json.

Pure domain — pydantic + stdlib only. `final_json` validates against a lightweight
**pydantic-native** shape (not full JSON Schema): no new dependency, strictly
domain-pure, and pydantic's structured errors distinguish a shape violation from
unparseable JSON. `final_matches` compiles the regex at validate time so an invalid
pattern is a spec error before any run.

**On catastrophic backtracking:** stdlib `re` holds the GIL during a match and
cannot be interrupted in-process (thread and signal timeouts both fail), and an
input-length cap does not help (backtracking is exponential in tiny inputs). So the
pattern runs uncapped — a catastrophic one is the user's own regex in their own
suite, the same stance dryfire takes on passthrough mocks (SPIKE-004: no sandbox,
because pretending otherwise gives false assurance). Documented, not hidden.

Every failure carries the ordered tool-call trajectory (SPEC §6).
"""

from __future__ import annotations

import json
import re
from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, RootModel, create_model, field_validator

from dryfire.domain.assertions.base import AssertionResult, register
from dryfire.domain.assertions.trajectory import render_trajectory
from dryfire.domain.model.trace import Trace

# -- min_tool_calls ---------------------------------------------------------


class _MinSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    tool: str
    count: int


@register
class MinToolCalls:
    """A tool is called at least `count` times — the retry-recovery assertion."""

    kind: ClassVar[str] = "min_tool_calls"
    Args = _MinSpec

    def __init__(self, args: _MinSpec) -> None:
        self._tool = args.tool
        self._min = args.count

    def evaluate(self, trace: Trace) -> AssertionResult:
        calls = trace.tool_names().count(self._tool)
        passed = calls >= self._min
        return AssertionResult(
            kind=self.kind, description=f"min_tool_calls: {self._tool} × {self._min}",
            passed=passed,
            message=(
                "" if passed
                else f"{self._tool} was called {calls} times, need at least {self._min}"
            ),
            expected=f"{self._tool} called at least {self._min} times",
            actual=render_trajectory(trace),
        )


# -- final_matches ----------------------------------------------------------


@register
class FinalMatches:
    """The final text matches a regex (searched, not fullmatched). The pattern is
    compiled at validate time, so an invalid regex is a positioned spec error."""

    kind: ClassVar[str] = "final_matches"

    class Args(RootModel[str]):
        @field_validator("root")
        @classmethod
        def _compilable(cls, value: str) -> str:
            try:
                re.compile(value)
            except re.error as exc:  # a bad pattern is a spec error at validate time
                raise ValueError(f"invalid regex {value!r}: {exc}") from exc
            return value

    def __init__(self, args: Any) -> None:
        self._source: str = args.root
        self._pattern = re.compile(args.root)

    def evaluate(self, trace: Trace) -> AssertionResult:
        # Uncapped by design: a catastrophic pattern is the user's own regex (see
        # the module docstring). Runs in-process on the (small) final text.
        passed = self._pattern.search(trace.final_text or "") is not None
        return AssertionResult(
            kind=self.kind, description=f"final_matches: {self._source!r}", passed=passed,
            message="" if passed else f"no match for {self._source!r} in final text",
            expected=f"final text matches {self._source!r}",
            actual=render_trajectory(trace),
        )


# -- final_json -------------------------------------------------------------

_TYPE_MAP: dict[str, Any] = {
    "str": str, "int": int, "float": float, "number": float,
    "bool": bool, "object": dict, "array": list, "any": object,
}


class _JsonSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    required: list[str] = []
    fields: dict[str, str] = {}

    @field_validator("fields")
    @classmethod
    def _known_types(cls, value: dict[str, str]) -> dict[str, str]:
        bad = {t for t in value.values() if t not in _TYPE_MAP}
        if bad:
            raise ValueError(
                f"unknown field type(s) {sorted(bad)}; expected one of {sorted(_TYPE_MAP)}"
            )
        return value


@register
class FinalJson:
    """The final text, parsed as JSON, matches a pydantic-native shape (a documented
    subset: required keys + per-field types). Not full JSON Schema."""

    kind: ClassVar[str] = "final_json"
    Args = _JsonSpec

    def __init__(self, args: _JsonSpec) -> None:
        model_fields: dict[str, Any] = {}
        for name, type_str in args.fields.items():
            py_type = _TYPE_MAP[type_str]
            required = name in args.required
            model_fields[name] = (py_type, ...) if required else (py_type | None, None)
        for name in args.required:
            if name not in args.fields:
                model_fields[name] = (Any, ...)  # required, any type
        self._model = create_model("FinalJsonShape", **model_fields)

    def evaluate(self, trace: Trace) -> AssertionResult:
        trajectory = render_trajectory(trace)
        description = "final_json"
        expected = "final text is JSON matching the declared shape"
        text = trace.final_text or ""
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return AssertionResult(
                kind=self.kind, description=description, passed=False,
                message=f"final text is not valid JSON: {exc}",
                expected=expected, actual=trajectory,
            )
        try:
            self._model.model_validate(parsed)
        except Exception as exc:  # noqa: BLE001 - a shape mismatch is a failure, not a crash
            return AssertionResult(
                kind=self.kind, description=description, passed=False,
                message=f"JSON does not match the declared shape: {exc}",
                expected=expected, actual=trajectory,
            )
        return AssertionResult(
            kind=self.kind, description=description, passed=True, message="",
            expected=expected, actual=trajectory,
        )
