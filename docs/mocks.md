# Mocks

dryfire replaces every tool the agent calls with a **deterministic mock**, so a suite
runs offline, fast, and the same way every time. A mock is one or more rules per tool
name, matched **in order, first match wins**.

```yaml
mocks:
  lookup_order:
    - when: {order_id: "A-991"}     # optional deep-subset guard on the parsed args
      return: {tier: "gold"}        # deliver this as the tool result
    - return: {tier: "standard"}    # catch-all (no `when`)
  issue_refund:
    - error: "refund service unavailable"   # deliver an error tool result
  flaky_tool:
    - sequence:                     # one entry consumed per matching call
        - error: "timeout"          # first call fails…
        - return: {ok: true}        # …retry succeeds (last entry repeats)
```

Each rule carries **exactly one** outcome: `return`, `error`, `sequence`, or `impl`.

- **`return: <any>`** — value delivered as the tool result content (`return: null` is a
  legitimate empty result, distinct from an absent one).
- **`error: "message"`** — an error tool result (`is_error=True`).
- **`sequence: [...]`** — consumed one entry per matching call, in order; the last entry
  repeats once exhausted. This is what makes error-recovery testing first-class.
- **`impl: pkg.mod:func`** — a **passthrough** mock: run real Python code. See below.

Case-level `mocks` **replace** the whole rule list for a tool name (they do not append to
the suite's).

---

## Passthrough mocks (`impl:`) — v0.2

Instead of a canned value, a rule can name a real Python callable. dryfire imports it and
calls it with the tool's arguments, and the return value becomes the tool result.

```yaml
mocks:
  create_ticket:
    - impl: mytools.impls:create_ticket    # package.module:function
```

```python
# mytools/impls.py — resolved from your repo (the CWD is on sys.path)
def create_ticket(args: dict) -> dict:
    return {"id": 42, "title": args["title"], "status": "open"}
```

**Calling convention.** The callable receives the parsed tool arguments as **one positional
dict** — `func(args)`, never `func(**args)`, because JSON object keys are not guaranteed to
be valid Python identifiers. Return anything JSON-representable; a non-string/dict return is
rendered as JSON text.

**Sync or async.** Both work. A **sync** callable runs off the event loop (in a thread) so a
blocking call never stalls the other concurrent cases; an **async** callable is awaited
natively. You never have to make your function `async`.

**Failures don't crash the run.** If the callable raises, that tool call becomes an error
result (`is_error=True`) carrying the exception message, and the run continues — exactly like
an `error:` rule.

**Timeouts.** Each call is bounded (default **30 s**; set per rule with `timeout_s`). A hang
produces an error result. Note the bound is on the *wait*: a wedged **sync** callable cannot
be killed (Python has no thread-kill), so it keeps running in its thread until it returns —
the process joins it at shutdown. Async callables are cancelled cleanly.

**Validation catches a bad `impl:` early.** `dryfire validate` resolves every `impl:` (imports
the module, checks the attribute is callable) and reports a bad one as a **positioned spec
error** — file, line, and column — **before any API spend**. Importing the module runs its
top-level code (see the security note); dryfire itself makes no network call while validating.

**Passthrough results are never cached.** A real callable can have side effects and
non-deterministic output, so recording it into a cassette would make replay a lie. A case that
uses any passthrough mock is **excluded from cassette recording**, with a visible note in the
output. (Regular `return`/`error`/`sequence` mocks are unaffected — they're already
deterministic and cost nothing to recompute.)

### Security posture — read this before pointing `impl:` anywhere

> **Passthrough mocks run your code, unsandboxed.** When a mock uses
> `impl: package.module:function`, dryfire imports that module — running its top-level code —
> at `validate` time, and calls the function during a run with the arguments the model
> produced. This is arbitrary Python executing in the dryfire process with no isolation.
> That is deliberate: it is your own code in your own repository, and a sandbox that can be
> trivially escaped is worse than an honest "this runs your code." Point `impl:` only at code
> you trust and control, treat a suite file containing `impl:` exactly as you would a script
> you'd run directly, and let your CI environment — not dryfire — be the isolation boundary.
