"""SPIKE-001 — exercise both adapters across the three required scenarios.

    python probe.py --provider anthropic --dry-run     # offline, canned payloads
    python probe.py --provider anthropic               # live (needs API key)

--dry-run answers the structural question (does the neutral model hold?) using
recorded-shape payloads. The live run confirms the canned payloads match reality.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

from adapters import ADAPTERS
from neutral import Message, ToolCall, ToolDef, ToolResult

TOOLS = [
    ToolDef(name="lookup_order", description="Retrieve order details by ID.",
            input_schema={"type": "object",
                          "properties": {"order_id": {"type": "string"}},
                          "required": ["order_id"]}),
    ToolDef(name="check_inventory", description="Check stock for a SKU.",
            input_schema={"type": "object",
                          "properties": {"sku": {"type": "string"}},
                          "required": ["sku"]}),
]

SYSTEM = "You are a support agent. Use tools to answer. Be brief."

SCENARIOS = {
    "a_single_tool_call": "Look up order A-991.",
    "b_parallel_tool_calls":
        "Look up order A-991 AND check inventory for SKU-7 at the same time. "
        "Call both tools in one turn.",
    "c_error_then_retry": "Look up order A-991.",
}

# --------------------------------------------------------------------------
# Canned payloads: real response SHAPES for offline structural testing.
# --------------------------------------------------------------------------

CANNED = {
    "anthropic": {
        "a_single_tool_call": {
            "id": "msg_01", "type": "message", "role": "assistant",
            "model": "claude-sonnet-4-6",
            "content": [
                {"type": "text", "text": "Let me look that up."},
                {"type": "tool_use", "id": "toolu_01A", "name": "lookup_order",
                 "input": {"order_id": "A-991"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 512, "output_tokens": 64,
                      "cache_read_input_tokens": 0, "cache_creation_input_tokens": 0},
        },
        "b_parallel_tool_calls": {
            "id": "msg_02", "role": "assistant", "content": [
                {"type": "tool_use", "id": "toolu_01B", "name": "lookup_order",
                 "input": {"order_id": "A-991"}},
                {"type": "tool_use", "id": "toolu_01C", "name": "check_inventory",
                 "input": {"sku": "SKU-7"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 530, "output_tokens": 92},
        },
        "c_error_then_retry": {
            "id": "msg_03", "role": "assistant", "content": [
                {"type": "text", "text": "The lookup failed; retrying."},
                {"type": "tool_use", "id": "toolu_01D", "name": "lookup_order",
                 "input": {"order_id": "A-991"}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 610, "output_tokens": 71},
        },
    },
    "openai": {
        "a_single_tool_call": {
            "id": "chatcmpl-01", "choices": [{
                "index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "call_a1", "type": "function",
                     "function": {"name": "lookup_order",
                                  "arguments": '{"order_id":"A-991"}'}}]},
            }],
            "usage": {"prompt_tokens": 498, "completion_tokens": 22,
                      "prompt_tokens_details": {"cached_tokens": 0}},
        },
        "b_parallel_tool_calls": {
            "id": "chatcmpl-02", "choices": [{
                "index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": None, "tool_calls": [
                    {"id": "call_b1", "type": "function",
                     "function": {"name": "lookup_order",
                                  "arguments": '{"order_id":"A-991"}'}},
                    {"id": "call_b2", "type": "function",
                     "function": {"name": "check_inventory",
                                  "arguments": '{"sku":"SKU-7"}'}}]},
            }],
            "usage": {"prompt_tokens": 512, "completion_tokens": 44},
        },
        "c_error_then_retry": {
            "id": "chatcmpl-03", "choices": [{
                "index": 0, "finish_reason": "tool_calls",
                "message": {"role": "assistant", "content": "Retrying.",
                            "tool_calls": [
                                {"id": "call_c1", "type": "function",
                                 "function": {"name": "lookup_order",
                                              "arguments": '{"order_id":"A-991"}'}}]},
            }],
            "usage": {"prompt_tokens": 604, "completion_tokens": 31},
        },
    },
}

MODELS = {"anthropic": "claude-sonnet-4-6", "openai": "gpt-4.1-mini"}


def live_call(provider: str, payload: dict) -> dict:
    if provider == "anthropic":
        from anthropic import Anthropic
        client = Anthropic()
        return client.messages.create(**payload).model_dump()
    from openai import OpenAI
    return OpenAI().chat.completions.create(**payload).model_dump()


def run(provider: str, dry_run: bool) -> int:
    adapter = ADAPTERS[provider]
    failures = 0

    for scenario, prompt in SCENARIOS.items():
        print(f"\n{'=' * 70}\n{provider} :: {scenario}\n{'=' * 70}")

        messages = [Message(role="user", content=prompt)]

        # Scenario (c): pre-seed an assistant turn plus a FAILED tool result,
        # so we test that an error result round-trips and the model retries.
        if scenario == "c_error_then_retry":
            failed_call = ToolCall(id="toolu_seed" if provider == "anthropic"
                                   else "call_seed",
                                   name="lookup_order",
                                   arguments={"order_id": "A-991"})
            messages += [
                Message(role="assistant", content=None, tool_calls=[failed_call]),
                Message(role="user", tool_results=[
                    ToolResult(call_id=failed_call.id,
                               content="payment gateway timeout", is_error=True)]),
            ]

        params = {"model": MODELS[provider], "max_tokens": 512, "temperature": 0}
        payload = adapter.to_wire(system=SYSTEM, messages=messages,
                                  tools=TOOLS, params=params)
        print("--- REQUEST -------------------------------------------------")
        print(json.dumps(payload, indent=2)[:1400])

        raw = CANNED[provider][scenario] if dry_run else live_call(provider, payload)
        resp = adapter.from_wire(raw)

        print("--- NEUTRAL ModelResponse -----------------------------------")
        print(f"  text          : {resp.text!r}")
        print(f"  stop_reason   : {resp.stop_reason}")
        print(f"  usage         : in={resp.usage.input_tokens} "
              f"out={resp.usage.output_tokens} "
              f"cache_r={resp.usage.cache_read_tokens}")
        for c in resp.tool_calls:
            flag = "  ⚠ MALFORMED" if c.malformed_arguments else ""
            print(f"  tool_call     : {c.name}({c.arguments}) id={c.id}{flag}")

        # ---- structural checks --------------------------------------------
        expect_n = 2 if scenario == "b_parallel_tool_calls" else 1
        checks = [
            ("stop_reason maps to tool_use", resp.stop_reason == "tool_use"),
            (f"{expect_n} tool call(s) returned", len(resp.tool_calls) == expect_n),
            ("all arguments parsed to dict",
             all(isinstance(c.arguments, dict) for c in resp.tool_calls)),
            ("all call ids present",
             all(bool(c.id) for c in resp.tool_calls)),
        ]
        if scenario == "b_parallel_tool_calls":
            checks.append(("parallel calls preserve order",
                           [c.name for c in resp.tool_calls]
                           == ["lookup_order", "check_inventory"]))
        if scenario == "c_error_then_retry":
            sent = json.dumps(payload)
            checks.append(("error result survived to_wire",
                           "timeout" in sent))
            checks.append(("error is flagged, not just prose",
                           '"is_error": true' in sent or "ERROR:" in sent))

        print("--- CHECKS ---------------------------------------------------")
        for label, ok in checks:
            print(f"  {'PASS' if ok else 'FAIL'}  {label}")
            failures += not ok

    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=sorted(ADAPTERS), required=True)
    ap.add_argument("--dry-run", action="store_true",
                    help="use canned payloads; no network, no API key")
    args = ap.parse_args()

    if not args.dry_run:
        key = {"anthropic": "ANTHROPIC_API_KEY", "openai": "OPENAI_API_KEY"}[args.provider]
        if not os.environ.get(key):
            print(f"{key} not set. Use --dry-run for the offline structural test.",
                  file=sys.stderr)
            return 2

    failures = run(args.provider, args.dry_run)
    print(f"\n{'=' * 70}")
    print(f"{provider_label(args)}: {failures} failed check(s)")
    return 1 if failures else 0


def provider_label(args) -> str:
    return f"{args.provider} ({'dry-run' if args.dry_run else 'LIVE'})"


if __name__ == "__main__":
    raise SystemExit(main())
