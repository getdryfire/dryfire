"""DF-203 — FileCassetteStore specifics: layout, atomic writes, path safety,
schema invalidation, and a stable-key body for small git diffs."""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dryfire.adapters.driven.cache.file_store import FileCassetteStore
from dryfire.application.ports.response_cache import CassetteRecord
from dryfire.domain.fingerprint import SCHEMA_VERSION
from dryfire.domain.model.message import ModelResponse, Usage

FIXED = datetime(2026, 7, 30, 14, 22, 10, tzinfo=UTC)


def _response(text: str = "hi") -> ModelResponse:
    return ModelResponse(
        text=text, tool_calls=[], stop_reason="end_turn",
        usage=Usage(input_tokens=3, output_tokens=5), latency_ms=42, raw={"id": "msg_1"},
    )


def _record(**over: Any) -> CassetteRecord:
    base: dict[str, Any] = dict(
        fingerprint="f0b4fbe056178ff6", suite="refund_agent",
        case="escalates_refund_over_limit", turn=0, provider="anthropic",
        model="claude-sonnet-4-6", request_digest={"messages": []}, response=_response(),
    )
    base.update(over)
    return CassetteRecord(**base)


def test_layout_is_suite_case_turn_fingerprint(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    store.put(_record(turn=3), recorded_at=FIXED)
    case_dir = tmp_path / "refund_agent" / "escalates_refund_over_limit"
    assert (case_dir / "03-f0b4fbe056178ff6.json").is_file()


def test_body_carries_the_human_fields(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    store.put(_record(), recorded_at=FIXED)
    body = json.loads(next(tmp_path.rglob("*.json")).read_text(encoding="utf-8"))
    assert body["schema_version"] == SCHEMA_VERSION
    assert body["recorded_at"] == "2026-07-30T14:22:10Z"
    assert body["request_digest"] == {"messages": []}
    assert body["response"]["text"] == "hi"


def test_interrupted_write_leaves_no_partial_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileCassetteStore(tmp_path)

    def boom(src: str, dst: str) -> None:
        raise OSError("rename failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError):
        store.put(_record(), recorded_at=FIXED)

    # No target file, and no leftover temp file either.
    assert list(tmp_path.rglob("*.json")) == []
    assert list(tmp_path.rglob("*.tmp")) == []


def test_similar_names_do_not_collide(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    # Three distinct case names; two sanitise to the same base "a_b".
    store.put(_record(case="a/b", fingerprint="1111111111111111"), recorded_at=FIXED)
    store.put(_record(case="a:b", fingerprint="2222222222222222"), recorded_at=FIXED)
    store.put(_record(case="a_b", fingerprint="3333333333333333"), recorded_at=FIXED)

    assert store.get("1111111111111111") is not None
    assert store.get("2222222222222222") is not None
    assert store.get("3333333333333333") is not None
    # Three distinct files on disk — nothing was overwritten.
    assert len(list(tmp_path.rglob("*.json"))) == 3


def test_mismatched_schema_version_reads_as_a_miss(tmp_path: Path) -> None:
    store = FileCassetteStore(tmp_path)
    store.put(_record(), recorded_at=FIXED)
    path = next(tmp_path.rglob("*.json"))
    body = json.loads(path.read_text(encoding="utf-8"))
    body["schema_version"] = SCHEMA_VERSION + 999
    path.write_text(json.dumps(body), encoding="utf-8")

    assert store.get("f0b4fbe056178ff6") is None


def test_body_is_stable_key_json_small_diff_on_response_change(tmp_path: Path) -> None:
    a = FileCassetteStore(tmp_path / "a")
    b = FileCassetteStore(tmp_path / "b")
    a.put(_record(response=_response("original")), recorded_at=FIXED)
    b.put(_record(response=_response("changed")), recorded_at=FIXED)

    text_a = next((tmp_path / "a").rglob("*.json")).read_text(encoding="utf-8").splitlines()
    text_b = next((tmp_path / "b").rglob("*.json")).read_text(encoding="utf-8").splitlines()

    differing = [i for i, (x, y) in enumerate(zip(text_a, text_b, strict=True)) if x != y]
    # Only the response's text line changed; everything else is byte-identical.
    assert len(differing) == 1
    assert "original" in text_a[differing[0]] and "changed" in text_b[differing[0]]
