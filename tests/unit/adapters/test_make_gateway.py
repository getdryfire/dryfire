"""#71 — `make_gateway` provider selection, including the OpenAI-compatible registry.

`make_gateway` is the one place a concrete real provider is chosen (composition root).
These offline tests pin: the named compat providers resolve to an OpenAI-shaped gateway
carrying the right identity + base_url, a missing key is a *skip* signal (MissingCredentials)
naming the exact env var, and an unknown provider is a config error.
"""

from __future__ import annotations

import sys
import types
from typing import Any

import pytest

from dryfire import composition
from dryfire.composition import ConfigError, MissingCredentials, make_gateway


class _RecordingClient:
    last_kwargs: dict[str, Any] = {}

    def __init__(self, **kwargs: Any) -> None:
        _RecordingClient.last_kwargs = kwargs


@pytest.fixture(autouse=True)
def fake_openai_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    module = types.ModuleType("openai")
    module.AsyncOpenAI = _RecordingClient  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", module)
    _RecordingClient.last_kwargs = {}


def test_xai_reference_provider_resolves_to_an_openai_shaped_gateway(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("XAI_API_KEY", "sk-xai")
    gateway = make_gateway("xai")
    assert gateway.name == "xai"
    assert _RecordingClient.last_kwargs["base_url"] == "https://api.x.ai/v1"
    assert _RecordingClient.last_kwargs["api_key"] == "sk-xai"


def test_openrouter_is_registered_as_a_compat_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or")
    gateway = make_gateway("openrouter")
    assert gateway.name == "openrouter"
    assert _RecordingClient.last_kwargs["base_url"] == "https://openrouter.ai/api/v1"


def test_missing_compat_key_is_a_skip_naming_its_env_var(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(MissingCredentials) as exc:
        make_gateway("xai")
    assert exc.value.provider == "xai"
    assert exc.value.env_var == "XAI_API_KEY"


def test_unknown_provider_is_a_config_error() -> None:
    with pytest.raises(ConfigError, match="unknown provider"):
        make_gateway("nope")


def test_registry_is_data_not_code(monkeypatch: pytest.MonkeyPatch) -> None:
    # Adding a compat provider must be a registry row, not a new branch: every entry
    # shares one construction path. Prove the table is the source of truth.
    assert set(composition.OPENAI_COMPATIBLE) >= {"xai", "openrouter"}
    for name, spec in composition.OPENAI_COMPATIBLE.items():
        monkeypatch.setenv(spec.env_var, "sk-test")
        assert make_gateway(name).name == name
