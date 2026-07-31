# SPIKE-003 — FINDINGS

**Question:** can pydantic v2 error paths be mapped back to YAML line/col reliably enough
to hit the sub-60-second onboarding target?

**Answer: yes.** `ruamel.yaml` round-trip mode carries the position data we need and the
mapping is ~60 lines of code. Executed and verified — see `locate.py`, `render.py`,
`sample_broken.eval.yaml`.

---

## Verified output

All five required error classes are reported in a single pass, sorted by source position:

```
error: unknown field 'modle'
  --> sample_broken.eval.yaml:5:1   (modle)
     |
   5 | modle: claude-sonnet-4-6
     | ^

error: expected an integer
  --> sample_broken.eval.yaml:6:1   (max_turns)
     |
   6 | max_turns: six
     | ^

error: $ref target not found: ./schemas/escalate_to_humann.json
  --> sample_broken.eval.yaml:22:5   (tools[1].$ref)
      |
   22 |   - $ref: ./schemas/escalate_to_humann.json
      |     ^
   = help: did you mean ./schemas/escalate_to_human.json?

error: unknown assertion kind: 'calls_tolo'
  --> sample_broken.eval.yaml:34:9   (cases[0].expect[1].calls_tolo)
      |
   34 |       - calls_tolo: escalate_to_human
      |         ^
   = help: did you mean 'calls_tool'?

error: required field 'input' is missing
  --> sample_broken.eval.yaml:37:5   (cases[1].input)
      |
   37 |   - name: missing_input_field
      |     ^  (nearest enclosing node)
```

Exit code 2, per SPEC §7.1.

---

## Answers to the spike's questions

### 1. Can every pydantic error path be resolved to a position?

No — and it doesn't need to. Two distinct cases:

- **Resolvable (exact).** The loc path exists in the document: wrong types, unknown fields,
  bad nested values. Position points at the offending **key token**.
- **Unresolvable (fallback).** `missing` errors by definition name a key that isn't in the
  source, so there is nothing to point at. Union-tag segments injected by pydantic are
  likewise not navigable.

The fallback is the important design decision: walk as deep as the document allows, then
report the **deepest resolved ancestor** flagged `exact=False` and rendered with the note
`(nearest enclosing node)`. For a case missing `input`, this points at that case's `name:`
line — which is exactly where the user needs to look. This behaviour is strictly better
than pointing at the file root and is the reason `Position` carries an `exact` flag.

### 2. Performance cost on a 500-line suite

Measured on a synthesised 488-line suite, mean of 20 runs:

| Loader | Time |
|---|---|
| `ruamel.yaml` round-trip | 74.9 ms |
| `pyyaml.safe_load` | 34.3 ms |

**2.2× overhead, ~40 ms absolute.** Irrelevant — a single provider call is 1–5 seconds.
Adopt round-trip loading unconditionally; do not build a fast path.

### 3. Does this force a hard dependency?

Yes. **`ruamel.yaml` is a required core dependency, not optional**, and `pyyaml` must not
be used anywhere in the spec-loading path. SPEC §8.1 already lists it; this spike confirms
it is load-bearing rather than incidental.

Rejected alternatives: `yaml.compose()` gives a node tree with marks but requires
hand-rolling the entire mapping-to-python conversion to keep them attached — strictly more
code for the same result. A custom `SafeLoader` subclass that stamps `__line__` onto dicts
pollutes the data with keys pydantic's `extra="forbid"` then rejects.

### 4. Recommended module boundary

Three-stage pipeline, and the ordering is the real finding:

```
load_positioned()          ruamel round-trip -> node tree with .lc
        ↓
PRE-PASS 1: resolve_refs()      $ref loading; records its own SpecErrors
        ↓
PRE-PASS 2: registry check      unknown assertion kinds + did-you-mean
        ↓
MAIN PASS:  pydantic            structural validation
        ↓
locate() + render()             loc -> Position -> caret output
```

Both pre-passes must run **before** pydantic, because pydantic models declare
`extra="forbid"` and would reject a raw `$ref` key outright, masking the real error. And
assertion kinds are registry-driven (SPEC §6.3), so pydantic cannot check them at all —
that check is inherently a separate pass.

Proposed placement for AC-004:

- `spec/positions.py` — `Position`, `load_positioned`, `locate`. Zero knowledge of the
  spec schema. Directly liftable from `locate.py`.
- `spec/errors.py` — `SpecError`, the pydantic-code → plain-language message table, and
  the renderer.
- `spec/loader.py` — orchestrates the pipeline; owns `$ref` and env interpolation.

---

## Defect found and fixed during the spike

A failed `$ref` was replaced by an empty placeholder so validation could continue — but
pydantic then reported `tools[1].name` and `tools[1].input_schema` as missing, producing
**three errors for one user mistake**. Cascade noise like this is exactly what makes
validators feel hostile.

Fix (implemented, `render.py`): record the loc prefix of every node whose `$ref` failed,
then suppress any pydantic error whose loc begins with that prefix. Error count on the
sample dropped 7 → 5.

**This must be an acceptance criterion on AC-004,** with a regression test. The same
principle generalises: any error that causes a substitution must suppress its own
downstream cascade.

---

## Verdict

The approach holds. Adopt as specified above.

**Amendments required to SPEC.md:**

1. **§8.1** — mark `ruamel.yaml` as a *required core* dependency with the note "round-trip
   mode required for positioned errors; `pyyaml` must not be used in the spec path."
2. **§4** — record the mandatory three-stage ordering (refs → registry → pydantic) as
   normative, not an implementation detail.
3. **§7.1** — no change; exit code 2 confirmed correct for this class.

**New acceptance criteria for AC-004:**

- [ ] All errors in a file are reported in one pass, sorted by source position.
- [ ] `missing`-class errors resolve to the nearest enclosing node and are visibly marked
      as approximate.
- [ ] A failed `$ref` produces exactly one error, with cascades suppressed (regression test).
- [ ] Unknown assertion kinds produce a did-you-mean suggestion via edit distance.
- [ ] `Position` carries an `exact: bool`; the renderer distinguishes the two cases.

**Reference implementation to lift:** `locate.py::locate` and `locate.py::Position`
verbatim; `render.py::render` as the output-format contract.
