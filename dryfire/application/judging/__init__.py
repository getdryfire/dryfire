"""Judging application layer (v0.3, EPIC-003): the judge evaluator.

Where the model call that grades a trace lives — the async, gateway-backed enrichment
stage of ARCHITECTURE §4.4. It routes through the same `ModelGateway` as the agent under
test (cassette-backed and retried for free), stays injected so tests use a fake, and
bounds judge concurrency independently of case concurrency.
"""

from dryfire.application.judging.evaluator import JudgeEvaluator, JudgeRequest

__all__ = ["JudgeEvaluator", "JudgeRequest"]
