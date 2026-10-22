"""Offline tests: a scripted fake provider stands in for the model.

Run with:  python -m unittest test_quote_context.py
"""

import json
import tempfile
import unittest
from pathlib import Path

import quote_context as qc

DOC = qc.Document(
    doc_id="d1",
    title="USDA Standardizes Grant and Cooperative Agreement Requirements",
    text="WASHINGTON - USDA today announced it is standardizing grant and "
         "cooperative agreement requirements across the department.\n"
         "> “Today’s action not only reduces government bureaucracy, "
         "it protects taxpayers,” said the Secretary.",
)
QUOTE = "Today’s action not only reduces government bureaucracy, it protects taxpayers"
EVIDENCE = "standardizing grant and cooperative agreement requirements"


class FakeProvider:
    name, model = "fake", "fake-1"

    def __init__(self, triage, resolve):
        self.replies = {"triage": triage, "resolve": resolve}
        self.calls = []

    def call(self, system, user, max_tokens):
        step = "triage" if system is qc.TRIAGE_SYSTEM else "resolve"
        self.calls.append(step)
        r = self.replies[step]
        return r if isinstance(r, str) else json.dumps(r)


def ins(anchor, body, evidence=EVIDENCE, position="after"):
    return qc.Insertion(anchor, body, evidence, position)


class Assembly(unittest.TestCase):
    def test_splices_after_anchor_with_curly_apostrophe_retyped(self):
        a = qc.build_quote_in_context(QUOTE, [ins("Today's action", EVIDENCE)], DOC.text, DOC.title)
        self.assertEqual(a.status, qc.Status.RESOLVED)
        self.assertEqual(a.text, "Today’s action [standardizing grant and cooperative "
                                 "agreement requirements] not only reduces government "
                                 "bureaucracy, it protects taxpayers")

    def test_before_frame(self):
        a = qc.build_quote_in_context("That's why we acted.", [ins("", "on grant rules", position="before")],
                                      DOC.text)
        self.assertEqual(a.text, "[on grant rules] That's why we acted.")

    def test_edge_punctuation_trimmed(self):
        a = qc.build_quote_in_context(QUOTE, [ins("Today's action", ", grant standards,")], DOC.text)
        self.assertIn("[grant standards]", a.text)

    def test_rejections_leave_quote_plain(self):
        cases = {
            qc.Status.FAILED_ANCHOR_NOT_FOUND: [ins("Yesterday's action", "x")],
            qc.Status.FAILED_ANCHOR_NOT_UNIQUE: [ins("t", "x")],
            qc.Status.FAILED_EVIDENCE_NOT_FOUND: [ins("Today's action", "x", evidence="not in the doc")],
            qc.Status.FAILED_INSERTION_FORMAT: [ins("Today's action", "one two three four five six "
                                                    "seven eight nine ten eleven twelve thirteen")],
            qc.Status.FAILED_TOO_MANY_INSERTIONS: [ins("Today's action", "x")] * 4,
            qc.Status.FAILED_OVERLAPPING_ANCHORS: [ins("Today's action", "x"), ins("action not", "y")],
        }
        for status, insertions in cases.items():
            with self.subTest(status):
                a = qc.build_quote_in_context(QUOTE, insertions, DOC.text, DOC.title)
                self.assertEqual(a.status, status)
                self.assertEqual(a.text, QUOTE)

    def test_evidence_from_title_counts(self):
        a = qc.build_quote_in_context(QUOTE, [ins("Today's action", "grant standards",
                                                  evidence="Standardizes Grant and Cooperative")],
                                      DOC.text, DOC.title)
        self.assertEqual(a.status, qc.Status.RESOLVED)

    def test_salvages_one_broken_object(self):
        raw = '[{"quote_id": "a", "x": 1}, {"quote_id": "b", "evidence": "said "hi""}]'
        self.assertEqual(qc._parse_json_list(raw), [{"quote_id": "a", "x": 1}])


class EndToEnd(unittest.TestCase):
    def rows(self):
        return [
            {"quote_id": "q1", "doc_id": "d1", "direct_quote": QUOTE},
            {"quote_id": "q2", "doc_id": "d1", "direct_quote": "USDA grants will be simpler."},
            {"quote_id": "q3", "doc_id": "d1", "direct_quote": "This [new] rule helps."},
        ]

    def test_full_run(self):
        fake = FakeProvider(
            triage=[{"quote_id": "q1", "needs_context": True, "expressions": ["Today's action"]},
                    {"quote_id": "q2", "needs_context": False, "expressions": []}],
            resolve=[{"quote_id": "q1", "status": "resolved",
                      "insertions": [{"position": "after", "anchor": "Today's action",
                                      "insertion": EVIDENCE, "evidence": EVIDENCE}]}],
        )
        out = qc.Contextualiser(fake).run(self.rows(), [DOC])
        self.assertEqual([r.final_status for r in out],
                         [qc.Status.RESOLVED, qc.Status.NOT_NEEDED_TRIAGE,
                          qc.Status.MANUAL_REVIEW_EXISTING_BRACKETS])
        self.assertIn(f"[{EVIDENCE}]", out[0].quote_in_context)
        self.assertEqual(out[1].quote_in_context, out[1].direct_quote)
        self.assertEqual(fake.calls, ["triage", "resolve"])

    def test_missing_id_and_bad_json_are_logged_not_dropped(self):
        fake = FakeProvider(triage="not json", resolve=[])
        out = qc.Contextualiser(fake).run(self.rows()[:2], [DOC])
        self.assertEqual({r.final_status for r in out}, {qc.Status.FAILED_TRIAGE_PARSE})

    def test_cache_replays_without_calling(self):
        fake = FakeProvider(triage=[{"quote_id": "q2", "needs_context": False}], resolve=[])
        with tempfile.TemporaryDirectory() as d:
            cache = qc.ResponseCache(d)
            qc.Contextualiser(fake, cache=cache).run(self.rows()[1:2], [DOC])
            qc.Contextualiser(fake, cache=cache).run(self.rows()[1:2], [DOC])
        self.assertEqual(fake.calls, ["triage"])

    def test_csv_round_trip(self):
        here = Path(__file__).parent / "examples"
        quotes = qc.load_quotes(here / "quotes.csv")
        docs = qc.load_documents(here / "documents.jsonl")
        fake = FakeProvider(triage=[], resolve=[])
        results = qc.Contextualiser(fake).run(quotes, docs)
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "out.csv"
            qc.write_output(p, quotes, results)
            self.assertIn("quote_in_context", p.read_text(encoding="utf-8").splitlines()[0])


if __name__ == "__main__":
    unittest.main()
