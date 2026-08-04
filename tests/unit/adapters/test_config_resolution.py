"""AC-005 — configuration resolution: precedence, discovery, globbing."""

from pathlib import Path

import pytest

from dryfire.adapters.driven.spec.config import (
    discover_config,
    glob_suites,
    load_project_config,
    resolve,
)
from dryfire.adapters.driven.spec.models import Case, Defaults, Suite

_PATH = Path("evals/s.eval.yaml")


def _suite(**over: object) -> Suite:
    base: dict[str, object] = {"name": "s", "cases": []}
    base.update(over)
    return Suite.model_validate(base)


def _case(**over: object) -> Case:
    base: dict[str, object] = {"name": "c", "input": "hi", "expect": []}
    base.update(over)
    return Case.model_validate(base)


class TestPrecedence:
    """max_turns exercised across every level; each overrides the one below."""

    def test_builtin_when_nothing_set(self) -> None:
        rc = resolve(suite=_suite(), case=_case(), suite_path=_PATH)
        assert rc.max_turns == 10

    def test_project_overrides_builtin(self) -> None:
        rc = resolve(
            suite=_suite(),
            case=_case(),
            suite_path=_PATH,
            project_defaults=Defaults(max_turns=8),
        )
        assert rc.max_turns == 8

    def test_suite_overrides_project(self) -> None:
        rc = resolve(
            suite=_suite(max_turns=6),
            case=_case(),
            suite_path=_PATH,
            project_defaults=Defaults(max_turns=8),
        )
        assert rc.max_turns == 6

    def test_case_overrides_suite(self) -> None:
        rc = resolve(
            suite=_suite(max_turns=6),
            case=_case(max_turns=4),
            suite_path=_PATH,
            project_defaults=Defaults(max_turns=8),
        )
        assert rc.max_turns == 4

    def test_override_beats_case(self) -> None:
        rc = resolve(
            suite=_suite(max_turns=6),
            case=_case(max_turns=4),
            suite_path=_PATH,
            project_defaults=Defaults(max_turns=8),
            overrides={"max_turns": 2},
        )
        assert rc.max_turns == 2


class TestProviderPrecedence:
    """provider is suite-level (AC-016): a `fake` suite and an `anthropic` suite
    coexist in one project; suite beats the project default."""

    def test_suite_provider_overrides_project_default(self) -> None:
        rc = resolve(
            suite=_suite(provider="fake"),
            case=_case(),
            suite_path=_PATH,
            project_defaults=Defaults(provider="anthropic"),
        )
        assert rc.provider == "fake"

    def test_project_provider_used_when_suite_is_silent(self) -> None:
        rc = resolve(
            suite=_suite(),
            case=_case(),
            suite_path=_PATH,
            project_defaults=Defaults(provider="openai"),
        )
        assert rc.provider == "openai"

    def test_run_override_beats_suite_provider(self) -> None:
        rc = resolve(
            suite=_suite(provider="fake"),
            case=_case(),
            suite_path=_PATH,
            overrides={"provider": "anthropic"},
        )
        assert rc.provider == "anthropic"


class TestBuiltinDefaults:
    def test_case_inheriting_nothing_gets_every_builtin(self) -> None:
        rc = resolve(suite=_suite(), case=_case(), suite_path=_PATH)
        assert rc.provider == "anthropic"
        assert rc.model == "claude-sonnet-4-6"
        assert rc.max_turns == 10
        assert rc.temperature == 0.0
        assert rc.on_unmocked == "error"

    def test_temperature_zero_is_respected_not_treated_as_unset(self) -> None:
        rc = resolve(
            suite=_suite(temperature=0.0),
            case=_case(),
            suite_path=_PATH,
            project_defaults=Defaults(temperature=0.7),
        )
        assert rc.temperature == 0.0

    def test_tools_are_converted_from_suite_specs(self) -> None:
        suite = _suite(
            tools=[{"name": "lookup_order", "input_schema": {"type": "object"}}]
        )
        rc = resolve(suite=suite, case=_case(), suite_path=_PATH)
        assert [t.name for t in rc.tools] == ["lookup_order"]
        assert rc.tools[0].input_schema == {"type": "object"}

    def test_identity_and_content_are_carried(self) -> None:
        rc = resolve(
            suite=_suite(name="refund", system="be nice"),
            case=_case(name="c1", input="hi", expect=[{"calls_tool": "x"}]),
            suite_path=_PATH,
        )
        assert rc.suite_name == "refund"
        assert rc.case_name == "c1"
        assert rc.suite_path == _PATH
        assert rc.system == "be nice"
        assert rc.input == "hi"
        assert rc.expect == [{"calls_tool": "x"}]


class TestPurity:
    def test_resolve_is_pure_equal_on_repeat(self) -> None:
        args = dict(
            suite=_suite(max_turns=6),
            case=_case(max_turns=4),
            suite_path=_PATH,
            project_defaults=Defaults(temperature=0.3),
            overrides={"model": "claude-opus-4-8"},
        )
        assert resolve(**args) == resolve(**args)  # type: ignore[arg-type]


class TestDiscovery:
    def test_finds_config_in_an_ancestor_from_a_subdirectory(self, tmp_path: Path) -> None:
        (tmp_path / "dryfire.yaml").write_text("version: 1\n", encoding="utf-8")
        sub = tmp_path / "a" / "b" / "c"
        sub.mkdir(parents=True)
        found = discover_config(sub)
        assert found is not None
        assert found.samefile(tmp_path / "dryfire.yaml")

    def test_returns_none_when_no_config_anywhere(self, tmp_path: Path) -> None:
        assert discover_config(tmp_path) is None

    def test_no_config_resolves_to_builtins_without_error(self, tmp_path: Path) -> None:
        assert discover_config(tmp_path) is None
        rc = resolve(suite=_suite(), case=_case(), suite_path=_PATH, project_defaults=None)
        assert rc.max_turns == 10
        assert rc.provider == "anthropic"


class TestProjectConfigLoading:
    def test_loads_a_valid_project_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dryfire.yaml"
        cfg.write_text(
            "version: 1\n"
            "defaults:\n"
            "  model: claude-sonnet-4-6\n"
            "  max_turns: 8\n"
            "suites:\n"
            "  - 'evals/**/*.eval.yaml'\n",
            encoding="utf-8",
        )
        config = load_project_config(cfg)
        assert config.version == 1
        assert config.defaults is not None
        assert config.defaults.max_turns == 8
        assert config.suites == ["evals/**/*.eval.yaml"]

    def test_loads_user_defined_openai_compatible_providers(self, tmp_path: Path) -> None:
        # #75: a `providers:` block defines custom OpenAI-compatible endpoints by name.
        cfg = tmp_path / "dryfire.yaml"
        cfg.write_text(
            "version: 1\n"
            "providers:\n"
            "  my-llm:\n"
            "    base_url: https://ep.example/v1\n"
            "    api_key_env: MY_LLM_API_KEY\n",
            encoding="utf-8",
        )
        config = load_project_config(cfg)
        assert config.providers["my-llm"].base_url == "https://ep.example/v1"
        assert config.providers["my-llm"].api_key_env == "MY_LLM_API_KEY"

    def test_custom_provider_rejects_unknown_keys(self, tmp_path: Path) -> None:
        # Strict models: a typo'd field is a user error, not silently dropped (AC-003).
        cfg = tmp_path / "dryfire.yaml"
        cfg.write_text(
            "version: 1\n"
            "providers:\n"
            "  my-llm:\n"
            "    base_url: https://ep.example/v1\n"
            "    api_key_env: MY_LLM_API_KEY\n"
            "    baseurl: oops\n",
            encoding="utf-8",
        )
        with pytest.raises(Exception, match="baseurl|extra|permitted|forbidden"):
            load_project_config(cfg)


class TestGlobbing:
    def test_patterns_resolve_relative_to_the_config_directory(self, tmp_path: Path) -> None:
        cfg = tmp_path / "dryfire.yaml"
        cfg.write_text("version: 1\n", encoding="utf-8")
        (tmp_path / "evals").mkdir()
        (tmp_path / "evals" / "a.eval.yaml").write_text("", encoding="utf-8")
        (tmp_path / "evals" / "sub").mkdir()
        (tmp_path / "evals" / "sub" / "b.eval.yaml").write_text("", encoding="utf-8")
        # A file outside the pattern must not be picked up.
        (tmp_path / "evals" / "notes.txt").write_text("", encoding="utf-8")

        found = glob_suites(cfg, ["evals/**/*.eval.yaml"])
        names = sorted(p.name for p in found)
        assert names == ["a.eval.yaml", "b.eval.yaml"]
