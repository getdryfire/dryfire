# SPIKE-004 — Passthrough mock execution model

**Status:** complete · **Time-box:** half day · **Consumed by:** DF-211
**Prototype:** `resolver.py` (import resolution), `invoke.py` (the invoker DF-211 adapts),
`sample_impls.py`, `test_passthrough.py` (17 tests, all green — `make spike-passthrough`).

---

## Verdict — the execution model

A passthrough mock names a real Python callable as `impl: pkg.mod:func`. dryfire resolves it
and calls it with the tool arguments. The model, decided and proven here:

1. **Resolution is `importlib.import_module(mod)` + `getattr(mod, func)`**, with the CWD put
   on `sys.path` so a user's `mytools.py` in their repo root resolves the same way `python -c`
   would from that directory. An editable-installed package is not a special case — it is on
   `sys.path` via its `.pth`, so it reduces to the same path.
2. **Resolution happens at `validate` time.** A bad `impl:` is a positioned spec error
   (exit 2) before any API spend. The only thing that cannot happen early is the *call*, which
   needs live tool args. (Q2.)
3. **The calling convention is `func(arguments: dict) -> Any`** — the tool arguments passed as
   one positional dict. JSON object keys are not guaranteed valid Python identifiers, so
   `func(**arguments)` is unsafe; `func(arguments)` always works. This is the impl signature
   DF-211 documents.
4. **Sync callables run in a thread** (`asyncio.to_thread`); **async callables are awaited
   natively**; a sync callable that *returns* an awaitable is also awaited. Users are NOT
   required to write async. (Q1.)
5. **A raise becomes `ToolResult(is_error=True)`** carrying the exception message; the run
   continues. `invoke()` never propagates a callable's own exception.
6. **A per-call timeout bounds a hang** (default **30 s**, Q3). This bounds the *scheduler*,
   not the *thread* — see the load-bearing nuance below.
7. **Passthrough results are never cached**, and a case that uses one is excluded from
   cassette *recording* with a visible note. (Q4.)

`invoke()` in `invoke.py` is the reference DF-211 adapts verbatim in shape.

### Load-bearing nuance discovered building this (do not rediscover)

`asyncio.wait_for` bounds the **wait**, not the **work**. Python cannot kill a thread, so a
wedged **sync** impl runs to completion:

- **While the event loop lives**, the timeout returns control to the loop at the bound. Other
  concurrent cases proceed on schedule — the scheduler is *not* blocked. Proven by
  `test_sync_hang_does_not_block_the_scheduler` (a fast neighbour completes while the hang is
  abandoned; wall-clock < 0.35 s for a 0.5 s hang bounded at 0.1 s).
- **At loop shutdown**, `asyncio.run` joins the default executor's threads, so the *process*
  still pays the abandoned thread's full runtime once at the end. Proven by
  `test_abandoned_sync_thread_is_joined_at_loop_shutdown`.

**Async** impls do not have this asymmetry: `wait_for` cancels the coroutine cleanly, no
thread, nothing to join (`test_async_hang_is_bounded_and_cancelled`). This asymmetry is real
and DF-211 must not paper over it — it is a direct consequence of the no-sandbox stance. It is
acceptable: the scheduler never deadlocks (the one hard constraint), and a wedged impl is the
user's own code hanging in the user's own CI.

---

## Acceptance criteria

| AC | Result | Proof |
|----|--------|-------|
| Resolves `pkg.mod:func` on `sys.path`, in CWD, in an editable install | ✅ | `test_resolves_module_on_syspath`, `test_resolves_from_cwd`; editable = the sys.path case |
| Sync callable invoked without blocking the loop (4×200 ms < 400 ms) | ✅ | `test_four_sync_impls_do_not_serialise` |
| Async callable invoked natively | ✅ | `test_async_callable_awaited_natively` |
| A raise → `ToolResult(is_error=True)`, run continues | ✅ | `test_raising_callable_becomes_error_result` |
| A hang is bounded by a timeout → error result | ✅ (scheduler bound; see nuance) | `test_sync_hang_does_not_block_the_scheduler`, `test_async_hang_is_bounded_and_cancelled` |
| Import failure = spec error at validate time, not a mid-run crash | ✅ | `test_bad_impl_is_reported_not_crashed`, `test_non_callable_attribute_is_rejected` |

---

## Questions the spike had to answer

### Q1 — Sync callables: thread executor, or require async?

**Thread executor (`asyncio.to_thread`).** Requiring users to rewrite existing sync functions
as `async def` is hostile — a passthrough impl is typically a plain function that already hits
a real API or reads a fixture. Running it inline would freeze the scheduler for every other
case at concurrency 4; running it in a thread keeps the loop free.

**Trade-off, stated honestly:** threads + the GIL mean a *CPU-bound* sync impl won't truly
parallelize, and (per the nuance above) a *wedged* sync impl cannot be killed and leaks a
thread until the process exits. Both are acceptable: passthrough impls are overwhelmingly
I/O-bound (the reason to reach for a real callable is a real side effect), and the no-sandbox
stance already says "this is your code." We take the thread executor and document the leak.

### Q2 — Can import resolution happen at `validate` time?

**Yes, and it must.** `importlib.import_module` + `getattr` need no tool args, so
`dryfire validate` resolves every `impl:` and reports a bad one as a positioned spec error
(exit 2) with zero network calls. The prototype proves the resolution and every failure mode
offline.

**The one case it cannot fully pre-empt:** importing the module *runs its top-level code*, so
a module whose import has side effects, or which only imports inside a fully-provisioned
runtime (needs env vars / a live DB at import), can pass or fail `validate` differently than at
run time. That is inherent to Python import and is disclosed in the security paragraph — we do
not try to defeat it. The callable's *body* still only runs during a real run, as expected.

### Q3 — Timeout default, and per-call or per-case?

**Per-call, default 30 s.** Per-call because the natural unit is one invocation of the
callable; a per-case bound would conflate several impl calls with the model round-trips and
make a timeout message useless. 30 s is generous enough not to false-trip a real API call yet
short enough that a hang cannot wedge a CI job. It is a constant on `invoke()` in the prototype;
DF-211 should make it overridable (a global `--passthrough-timeout` and/or per-mock field).

### Q4 — Is a passthrough result cacheable?

**No — confirmed with a concrete example.** `impl: mytools:create_ticket` POSTs to a real
ticketing API and returns the new ticket id. Record it once and (a) the id is frozen to a stale
value and (b) replay never creates the ticket — the cassette asserts against a side effect that
did not happen. A `now()`-based impl is worse: caching freezes the timestamp and the
"regression" test then passes against a lie. And because the model's next turn is fed the tool
result, a passthrough that returns a different value on replay shifts the message history the
completion cache is keyed on — you get a spurious cassette miss (or, if the key ignores it, a
cached model turn inconsistent with the live result). Every path makes replay unfaithful.

**Verdict:** passthrough results are never cached; a case using any passthrough mock is
excluded from cassette *recording* with a visible note (DF-211 AC). Replay of such a case runs
the impl live — there is nothing to replay for it.

### Q5 — Security posture, one paragraph for the docs

> **Passthrough mocks run your code, unsandboxed.** When a mock uses
> `impl: package.module:function`, dryfire imports that module — running its top-level code —
> at `validate` time, and calls the function during a run with the arguments the model
> produced. This is arbitrary Python executing in the dryfire process with no isolation.
> That is deliberate: it is your own code in your own repository, and a sandbox that can be
> trivially escaped is worse than an honest "this runs your code." Point `impl:` only at code
> you trust and control, treat a suite file containing `impl:` exactly as you would a script
> you'd run directly, and let your CI environment — not dryfire — be the isolation boundary.

---

## Layering — the seam DF-211 pays for (flagged, per the ticket)

Invocation is I/O and impure, so it **cannot live in `domain/`**. The clean shape:

- The **domain** `MockResolver` stays pure by resolving a passthrough rule to a *marker*
  outcome (a new frozen value, e.g. `Passthrough(target=..., timeout_s=...)`) — no import, no
  call. Resolution of the *string* to a callable is done once at validate time and can also
  stay pure-ish (it is a lookup), but the *call* cannot.
- A new **application port** — `ToolInvoker` (async, one method `invoke(marker, call) ->
  ToolResult`) — is implemented by a **driven adapter** wrapping `invoke.py`, wired in
  `composition.py`.

**This forces a small, contained change to `application/loop.py`** — and DF-211 must say so out
loud rather than smuggle I/O into the domain. Today the loop does `resolved = resolver.resolve(call)`
(sync) and branches on `UNMOCKED`. A passthrough marker adds one branch:

```python
resolved = resolver.resolve(call)
if isinstance(resolved, Passthrough):
    resolved = await invoker.invoke(resolved, call)   # the loop is already async
```

Note this is **not** covered by the epic's "loop unchanged" rule — that rule is specifically
about *gateway* decorators (caching/retrying) and is carried as an AC only by DF-201 and DF-204
(EPIC-002 §9). Passthrough is a tool-resolution behaviour, not a gateway behaviour; there is
**no** way to realize it without either I/O in the domain (forbidden) or this one branch at the
resolution seam. Recommend the branch + `ToolInvoker` port, and get the owner's explicit sign-off
on touching `loop.py` since the prior session treated the loop as frozen for all EPIC-002 work.

## Open surface question for DF-211 (not an execution-model question)

SPEC §4.4 frames passthrough as an `on_unmocked: passthrough` policy resolved via
`impl: pkg.mod:func`, but does not pin *where* `impl` attaches. Two plausible YAML surfaces:

- **(a)** case/suite-level `on_unmocked: passthrough` + one `impl:` that dispatches on tool
  name — a single fallback for every unmatched call.
- **(b)** a per-tool mock rule carrying `impl:` in place of `return/error/sequence` — precise,
  and a natural fit for the existing `MockRule` one-of.

The execution model above is identical for both. DF-211 should pick the surface (recommend **b**
for precision and consistency with the existing one-of validation) and amend SPEC §4.4 to say so.
