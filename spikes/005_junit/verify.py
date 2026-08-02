"""SPIKE-005 — the offline-decidable half of the JUnit mapping question.

What can be settled WITHOUT a live CI UI is settled here, authoritatively: XML
well-formedness, whether the `→` arrow and `✗` survive, entity escaping, and the
one that decides the mapping's shape — attribute-value newline normalization. What
CANNOT be settled offline (does dorny/GitLab/Jenkins truncate the body, does a
consumer render only the first <failure>) is documented in render_notes.md with a
throwaway-repo capture kit, because those live in the consumers' UIs, not the XML.

Run: `make spike-junit` (asserts; non-zero exit on any failure).

Every fact below is parser-independent: attribute-value normalization and entity
handling are mandated by XML 1.0 §3.3.3 / §4.6, so every conformant consumer —
expat here, Nokogiri in dorny, Go's encoding/xml in GitLab, Xerces in Jenkins —
sees the same thing. That is why these are safe to generalise from one parser.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET  # noqa: S405 - see note below
from pathlib import Path

# NOTE on stdlib XML: this script parses only the trusted, first-party candidate
# fixtures committed alongside it — never external or user-supplied XML — so the
# XXE / billion-laughs concerns that make `defusedxml` mandatory for untrusted
# input do not apply, and the spike stays stdlib-only (project dep philosophy:
# pydantic + stdlib). Relevant for DF-209: dryfire *emits* JUnit and never reads
# it, so the JUnit sink has no XML parse surface at all — the risk is structurally
# absent on the product path, not merely mitigated here.

HERE = Path(__file__).parent
CANDIDATES = HERE / "candidates"
ARROW = "→"  # →
CROSS = "✗"  # ✗


def _report(label: str, ok: bool, detail: str = "") -> bool:
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label}" + (f" — {detail}" if detail else ""))
    return ok


def check_well_formed() -> bool:
    print("1. All candidates are well-formed XML")
    ok = True
    for xml in sorted(CANDIDATES.glob("*.xml")):
        try:
            ET.parse(xml)
            ok &= _report(xml.name, True)
        except ET.ParseError as exc:
            ok &= _report(xml.name, False, str(exc))
    return ok


def check_arrow_survives() -> bool:
    print("2. The `→` trajectory arrow and `✗` survive as literal UTF-8 (Q5)")
    tree = ET.parse(CANDIDATES / "A.xml")
    failure = tree.find(".//testcase/failure")
    assert failure is not None and failure.text is not None
    body = failure.text
    a = _report("`→` present in the failure body", ARROW in body)
    # The arrow needs NO entity: it is a legal XML char in UTF-8. A consumer that
    # required ASCII would mojibake it; none in scope do (documented in FINDINGS Q5).
    raw = (CANDIDATES / "A.xml").read_text(encoding="utf-8")
    b = _report("`→` written literally in source, not as &#8594;", ARROW in raw)
    c = _report("`✗` (assertion bullet) round-trips", CROSS in body)
    return a and b and c


def check_entity_escaping() -> bool:
    print("3. `&` and `<` inside tool-arg JSON round-trip through escaping")
    tree = ET.parse(CANDIDATES / "A.xml")
    body = tree.find(".//testcase/failure").text  # type: ignore[union-attr]
    assert body is not None
    # Source escapes them as &amp; / &lt; / &gt;; the parser hands back the literals.
    a = _report('parsed body contains literal "R&D <flagged>"', "R&D <flagged>" in body)
    raw = (CANDIDATES / "A.xml").read_text(encoding="utf-8")
    b = _report("source stores them escaped (&amp;, &lt;)", "R&amp;D &lt;flagged&gt;" in raw)
    return a and b


def check_attribute_newline_normalization() -> bool:
    print("4. THE mapping-shaping fact: newlines survive in TEXT, collapse in an ATTRIBUTE")
    # XML 1.0 §3.3.3: during attribute-value normalization a literal newline (#xA)
    # is replaced by a space. Element text is not normalized. So a multi-line
    # trajectory block MUST live in the <failure> text, not its message="" attribute.
    doc = '<t a="line1\nline2">line1\nline2</t>'
    el = ET.fromstring(doc)
    attr_collapsed = _report(
        'literal newline in message="" collapses to a space',
        el.get("a") == "line1 line2",
        repr(el.get("a")),
    )
    text_preserved = _report(
        "the same newline in element text is preserved",
        el.text == "line1\nline2",
        repr(el.text),
    )
    # And confirm our recommended candidate (A) actually follows the rule.
    tree = ET.parse(CANDIDATES / "A.xml")
    fail = tree.find(".//testcase/failure")
    assert fail is not None
    body_multiline = _report(
        "A.xml keeps the multi-line block in <failure> TEXT",
        fail.text is not None and "\n" in fail.text,
    )
    summary_oneline = _report(
        'A.xml keeps message="" to a single line (no newline)',
        "\n" not in (fail.get("message") or ""),
    )
    return attr_collapsed and text_preserved and body_multiline and summary_oneline


def check_multiple_failures_risk() -> bool:
    print("5. Candidate C's multiple-<failure>-per-testcase risk is real, not theoretical")
    tree = ET.parse(CANDIDATES / "C.xml")
    failing = tree.find(".//testcase[@name='denies refund when policy check fails']")
    assert failing is not None
    failures = failing.findall("failure")
    all_present = _report(
        "C.xml emits 2 <failure> children under one <testcase>",
        len(failures) == 2,
        f"count={len(failures)}",
    )
    # A first-failure-only consumer (Ant/Surefire schema allows at most one) would
    # show only this and silently drop the escalate_to_human failure:
    first_only = failures[0].get("message")
    dropped = failures[1].get("message")
    print(f"       first-failure-only consumers see: {first_only!r}")
    print(f"       ...and SILENTLY DROP:              {dropped!r}")
    # Candidate A carries both in one body, so nothing can be dropped:
    a_tree = ET.parse(CANDIDATES / "A.xml")
    a_body = a_tree.find(".//testcase/failure").text  # type: ignore[union-attr]
    both_in_a = _report(
        "A.xml carries BOTH assertions in one <failure> body (nothing to drop)",
        a_body is not None
        and "not_calls_tool: issue_refund" in a_body
        and "calls_tool: escalate_to_human" in a_body,
    )
    return all_present and both_in_a


def check_zero_case_run() -> bool:
    print("6. Zero-case run parses and is distinguishable from a green run")
    tree = ET.parse(CANDIDATES / "zero_cases.xml")
    root = tree.getroot()
    parses = _report("zero_cases.xml is well-formed", root is not None)
    zero = _report(
        'tests="0" is present so a consumer CAN surface "no tests ran"',
        root.get("tests") == "0",
        "DF-209 must not let 0 tests read as a silent green — emit a note",
    )
    return parses and zero


def main() -> int:
    checks = [
        check_well_formed,
        check_arrow_survives,
        check_entity_escaping,
        check_attribute_newline_normalization,
        check_multiple_failures_risk,
        check_zero_case_run,
    ]
    all_ok = True
    for check in checks:
        all_ok &= check()
        print()
    print("=" * 60)
    print("OFFLINE VERDICT: all XML-decidable facts confirmed."
          if all_ok else "OFFLINE VERDICT: FAILURES ABOVE.")
    print("Live-UI legibility (truncation, first-<failure>-only) → render_notes.md kit.")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
