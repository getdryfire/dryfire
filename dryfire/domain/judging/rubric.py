"""`Rubric` and rubric hashing (DF-301).

A rubric is *what* the judge grades: the instruction text, the pass threshold, and any
few-shot examples. Its hash is the load-bearing part — it is the provenance a score
carries so that two scores are only ever compared when they were produced under the
same rubric. The single most common failure of LLM-as-judge systems is charting quality
over months while the rubric silently drifts; the hash makes that drift visible.

The hash **reuses** `domain/fingerprint.py`'s canonicaliser rather than a second hasher
that could diverge from it:

  STABLE    under dict key order (sorted-keys canonicalisation)
  SENSITIVE to any text change including whitespace, the threshold, and the examples

Rubric text is whitespace-significant on purpose: reformatting a rubric may change the
judgement, so it must change the hash. Pure domain: pydantic + stdlib only.
"""

from __future__ import annotations

import hashlib

from pydantic import BaseModel, ConfigDict

from dryfire.domain.fingerprint import canonical_json

# The default pass threshold when a rubric / `llm_judge` assertion does not name one.
# DF-303 exposes this as the assertion's documented default.
DEFAULT_JUDGE_THRESHOLD = 0.7


class Rubric(BaseModel):
    """What a judge grades. `text` is whitespace-significant. `examples` are optional
    few-shot exemplars; they are folded into the hash so a rubric that gains examples
    is not silently treated as the same rubric."""

    model_config = ConfigDict(frozen=True)

    text: str
    threshold: float = DEFAULT_JUDGE_THRESHOLD
    examples: tuple[str, ...] = ()

    def hash(self) -> str:
        """A stable SHA-256 hex digest over the rubric text, threshold, and examples,
        canonicalised the same way cassette fingerprints are (sorted keys, NFC text,
        no whitespace between tokens — but whitespace *within* the text preserved)."""
        payload = {
            "text": self.text,
            "threshold": self.threshold,
            "examples": list(self.examples),
        }
        return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()
