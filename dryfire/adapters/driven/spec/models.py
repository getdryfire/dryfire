"""Pydantic schema for suite and project-config files (SPEC §4).

This is the raw parse layer: what YAML validates into *after* $ref resolution and
env interpolation (AC-004) but *before* default resolution (AC-005). Overridable
fields are therefore ``| None`` — the built-in defaults are not baked in here.

`expect` entries stay as ``list[dict]``: assertion kinds are registry-driven
(SPEC §6.3) and cannot be checked by pydantic; that check is AC-004's pre-pass.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OnUnmocked = Literal["error", "null", "passthrough"]
CassetteMode = Literal["auto", "record", "replay", "off"]


class _StrictModel(BaseModel):
    """Every spec model forbids unknown keys — a stray key is a user error and
    must surface as one (AC-003)."""

    model_config = ConfigDict(extra="forbid")


class ToolSpec(_StrictModel):
    """A tool as written in a suite file. `$ref` forms are resolved to this
    shape by AC-004 before validation; a raw `$ref` reaching here is a bug."""

    name: str
    description: str | None = None
    input_schema: dict[str, Any]


_OUTCOME_FIELDS = ("returns", "error", "sequence", "impl")


class MockRule(_StrictModel):
    """One declarative fake-tool rule. Exactly one of return/error/sequence/impl.

    `returns` carries the YAML key `return` (a Python keyword) via alias;
    `populate_by_name` keeps `.returns` usable in code. `impl` names a real Python
    callable (`pkg.mod:func`) for a passthrough mock (SPEC §4.4, DF-211); it is
    resolved at validate time and invoked via the ToolInvoker port at run time.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    when: dict[str, Any] | None = None
    returns: Any | None = Field(default=None, alias="return")
    error: str | None = None
    sequence: list[dict[str, Any]] | None = None
    impl: str | None = None

    @model_validator(mode="after")
    def _exactly_one_outcome(self) -> "MockRule":
        set_outcomes = [f for f in _OUTCOME_FIELDS if f in self.model_fields_set]
        if len(set_outcomes) != 1:
            found = ", ".join(set_outcomes) if set_outcomes else "none"
            raise ValueError(
                "a mock rule needs exactly one of return/error/sequence/impl; found: " + found
            )
        return self


class ScriptToolCall(_StrictModel):
    """One scripted tool call inside a `script` step: the model asking to invoke
    `name` with `arguments` (AC-016). Used alone as a single-call turn or inside
    `parallel`."""

    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


_STEP_FIELDS = ("text", "tool_call", "parallel", "fails")


class ScriptStep(_StrictModel):
    """One scripted model turn for a `provider: fake` case (AC-016). Exactly one
    of text / tool_call / parallel / fails, mirroring the FakeGateway helpers.

    `fails` carries the error message for a simulated provider failure. Which
    field was set is detected via `model_fields_set`, like MockRule."""

    text: str | None = None
    tool_call: ScriptToolCall | None = None
    parallel: list[ScriptToolCall] | None = None
    fails: str | None = None

    @model_validator(mode="after")
    def _exactly_one_kind(self) -> "ScriptStep":
        set_kinds = [f for f in _STEP_FIELDS if f in self.model_fields_set]
        if len(set_kinds) != 1:
            found = ", ".join(set_kinds) if set_kinds else "none"
            raise ValueError(
                "a script step needs exactly one of text/tool_call/parallel/fails; "
                f"found: {found}"
            )
        return self


class Case(_StrictModel):
    """One executable scenario. `input` is a single user message (string) or a
    multi-turn setup (list of role/content dicts). Case-level `mocks` merge over
    the suite's at resolution time (AC-005); the model just carries them.

    Overridable settings (`model`, `max_turns`, `temperature`, `on_unmocked`) are
    the highest-precedence spec source and are ``| None`` until resolved (AC-005).

    `script` is the scripted model turns for a `provider: fake` case (AC-016);
    absent for real-provider cases.
    """

    name: str
    input: str | list[dict[str, Any]]
    expect: list[dict[str, Any]]
    mocks: dict[str, list[MockRule]] | None = None
    script: list[ScriptStep] | None = None
    model: str | None = None
    max_turns: int | None = None
    temperature: float | None = None
    on_unmocked: OnUnmocked | None = None


class Suite(_StrictModel):
    """One `*.eval.yaml` file: shared prompt, tools, mocks, and cases.

    Overridable defaults (`provider`, `model`, `max_turns`, `temperature`,
    `on_unmocked`) are ``| None`` — they fall back to the project config at AC-005.
    `provider` is suite-level so a `fake` suite and an `anthropic` suite can live
    in one project (AC-016).
    """

    name: str
    description: str | None = None
    tags: list[str] = []
    provider: str | None = None
    model: str | None = None
    max_turns: int | None = None
    temperature: float | None = None
    on_unmocked: OnUnmocked | None = None
    system: str | None = None
    tools: list[ToolSpec] = []
    mocks: dict[str, list[MockRule]] | None = None
    cases: list[Case]


class Defaults(_StrictModel):
    """The `defaults:` block of `dryfire.yaml`. All optional — an absent
    value falls back to a built-in default at AC-005, not here."""

    provider: str | None = None
    model: str | None = None
    max_turns: int | None = None
    temperature: float | None = None
    on_unmocked: OnUnmocked | None = None


class CassetteConfig(_StrictModel):
    """The `cassettes:` block. Cassettes themselves are v0.2; the schema exists
    now so config files validate."""

    dir: str | None = None
    mode: CassetteMode | None = None


class ProjectConfig(_StrictModel):
    """`dryfire.yaml` at the repo root."""

    version: int
    defaults: Defaults | None = None
    suites: list[str] = []
    cassettes: CassetteConfig | None = None
    pricing_file: str | None = None
