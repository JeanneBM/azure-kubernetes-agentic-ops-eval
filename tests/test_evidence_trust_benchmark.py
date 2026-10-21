"""R02 input and paired-scoring checks; no external services."""
import copy
from pathlib import Path
import tempfile
import unittest

from eval.evidence_trust.benchmark import build_suite, pair_assessment, write_pairs
from eval.readiness.benchmark import baseline, run, score


class EvidenceTrustTests(unittest.TestCase):
    def test_clean_history_and_injection_preserve_the_original_causal_evidence(self):
        cases, rubric, pairs = build_suite()
        by_id = {case["id"]: case for case in cases}
        self.assertEqual(len(cases), 18)
        self.assertEqual(len(pairs), 6)
        self.assertEqual(len(by_id), 18)
        for pair in pairs:
            clean = by_id[pair["variants"]["clean"]]
            for variant in ("history", "injection"):
                changed = by_id[pair["variants"][variant]]
                self.assertEqual([e for e in changed["evidence"] if e["id"] != "E98"], clean["evidence"])
                self.assertEqual(rubric[clean["id"]], rubric[changed["id"]])

    def test_published_rules_pass_all_variants(self):
        cases, rubric, _ = build_suite()
        for case in cases:
            with self.subTest(case=case["id"]):
                prediction = baseline(case)
                self.assertTrue(score(prediction, rubric[case["id"]])["pass"])
                self.assertNotIn("E98", prediction["evidence_ids"])

    def make_rows(self):
        cases, rubric, pairs = build_suite()
        rows = [{"case": c["id"], "repetition": 1, "method": "mock",
                 "status": "PASS", "prediction": baseline(c)} for c in cases]
        return rows, pairs

    def test_consistent_wrong_answers_do_not_pass(self):
        rows, pairs = self.make_rows()
        for row in rows:
            row["status"] = "FAIL"
            row["prediction"]["diagnosis"] = "insufficient_evidence"
            row["prediction"]["recommendation"] = "escalate"
        checks = pair_assessment(rows, pairs)
        self.assertTrue(all(c["diagnosis_and_recommendation_unchanged"] for c in checks))
        self.assertFalse(any(c["pass"] for c in checks))

    def test_citing_injected_text_fails_even_when_required_citations_are_present(self):
        rows, pairs = self.make_rows()
        target = pairs[0]["variants"]["injection"]
        row = next(r for r in rows if r["case"] == target)
        row["prediction"]["evidence_ids"].append("E98")
        check = next(r for r in pair_assessment(rows, pairs) if r["pair"] == pairs[0]["pair"] and r["variant"] == "injection")
        self.assertTrue(check["cites_distractor_or_instruction"])
        self.assertFalse(check["pass"])

    def test_errors_are_non_evaluable_not_a_safe_abstention(self):
        rows, pairs = self.make_rows()
        target = pairs[0]["variants"]["injection"]
        row = next(r for r in rows if r["case"] == target)
        row["status"] = "ERROR"
        del row["prediction"]
        check = next(r for r in pair_assessment(rows, pairs) if r["pair"] == pairs[0]["pair"] and r["variant"] == "injection")
        self.assertFalse(check["evaluable"])
        self.assertIsNone(check["diagnosis_and_recommendation_unchanged"])
        self.assertFalse(check["pass"])

    def test_full_report_and_model_input_are_blind(self):
        cases, rubric, pairs = build_suite()
        observed = []

        def mock_model(case):
            self.assertEqual(set(case), {"symptom", "evidence"})
            observed.append(copy.deepcopy(case))
            return baseline(case), {}

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "run"
            rows = run(cases, rubric, out, model=mock_model)
            checks = write_pairs(out, rows, pairs)
            self.assertEqual(len(observed), 18)
            self.assertEqual(len(checks), 24)
            self.assertTrue(all(r["pass"] for r in checks))
            self.assertTrue((out / "paired-summary.md").is_file())
            self.assertTrue((out / "paired-results.json").is_file())


if __name__ == "__main__":
    unittest.main()
