## Summary

Briefly describe what changed and why.

## Scope

- Ticket / spec reference: <!-- e.g. SPEC.md §3 · #issue -->
- Layer(s) touched: <!-- domain / application / adapters / docs / toolchain -->
- Out of scope:

## Changes

- 
- 
- 

## Testing

List the commands you ran and the result.

```bash
# example
make check          # lint + typecheck + arch + test — all green
make docker-check   # optional: same gate in a clean Linux container
```

## Quality gate

- [ ] `make check` passes locally
- [ ] New/changed tests run **offline** — no network, no API key, no `@pytest.mark.live` required for CI
- [ ] Architecture contracts kept (`make arch`) — no new import-linter exceptions
- [ ] No `unittest.mock` outside `tests/contracts/` (doubles only at port boundaries)
- [ ] Ubiquitous language respected (ARCHITECTURE §3) — no banned synonyms in code, output, or docs

## Scope discipline

- [ ] Nothing deferred to v0.3+ (llm_judge, compare, HTML report, repeat, export, streaming, any server/DB) was built
- [ ] No ARCHITECTURE §11 tripwires introduced (repository class, event bus, DI container, ABC-where-Protocol-works, …)

## Public contracts

- [ ] Exit codes (0/1/2/3) unchanged — **or** this PR is flagged as breaking
- [ ] YAML suite format unchanged — **or** SPEC.md §4 updated in this PR
- [ ] Trace JSON shape unchanged — **or** SPEC.md §3 updated in this PR

Details (if any box above needed the "or"):

- 

## Docs

- [ ] `docs/Progress.md` updated (work shipped / status moved)
- [ ] `docs/Learnings.md` appended (only if a non-obvious pitfall or pattern was discovered)
- [ ] SPEC.md / ARCHITECTURE.md amended if implemented behavior diverges from them

## Risks

- 

## Follow-ups

- 
