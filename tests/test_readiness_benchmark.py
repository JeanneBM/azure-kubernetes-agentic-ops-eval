"""Offline evaluation-contract checks; no Azure, model or cluster required."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from eval.readiness.benchmark import baseline, load_cases, run, score, validate_prediction


class ReadinessBenchmarkTests(unittest.TestCase):
    def test_rules_cover_four_causes_and_two_abstentions_without_id_lookup(self):
        cases, rubric = load_cases()
        self.assertEqual(len(cases), 6)
        for case in cases:
            with self.subTest(case=case["id"]):
                prediction = validate_prediction(baseline(case), case)
                self.assertTrue(score(prediction, rubric[case["id"]])["pass"])
                renamed = copy.deepcopy(case)
                renamed["id"] = "arbitrary"
                self.assertEqual(baseline(renamed), prediction)

    def test_release_evidence_is_required_for_regression(self):
        cases, _ = load_cases()
        case = copy.deepcopy(cases[0])
        case["evidence"] = [e for e in case["evidence"] if e["kind"] != "release_comparison"]
        self.assertEqual(baseline(case)["diagnosis"], "insufficient_evidence")

    def test_right_label_without_discriminating_citations_fails(self):
        cases, rubric = load_cases()
        prediction = baseline(cases[0])
        prediction["evidence_ids"] = ["E1"]
        assessment = score(prediction, rubric[cases[0]["id"]])
        self.assertTrue(assessment["diagnosis_correct"])
        self.assertFalse(assessment["pass"])

    def test_unknown_evidence_and_executable_fields_are_rejected(self):
        cases, _ = load_cases()
        value = baseline(cases[0])
        value["evidence_ids"] = ["invented"]
        with self.assertRaises(ValueError):
            validate_prediction(value, cases[0])
        value = baseline(cases[0])
        value["command"] = "kubectl delete deployment api"
        with self.assertRaises(ValueError):
            validate_prediction(value, cases[0])

    def test_blind_paired_inputs_errors_and_nonoverwriting_reports(self):
        cases, rubric = load_cases()
        seen = []

        def model(case):
            seen.append(copy.deepcopy(case))
            self.assertEqual(set(case), {"symptom", "evidence"})
            if len(seen) == 1:
                raise RuntimeError("simulated transport failure")
            return baseline(case), {"usage": {"total_tokens": 10}}

        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "run"
            rows = run(cases, rubric, output, model=model, repetitions=2)
            self.assertEqual(len(rows), 24)
            self.assertEqual(sum(r["status"] == "ERROR" for r in rows), 1)
            for i, case in enumerate(seen, start=1):
                a, b = rows[(i - 1) * 2:i * 2]
                self.assertEqual(a["input_sha256"], b["input_sha256"])
                self.assertEqual(json.loads((output / f"attempt-{i:03d}" / "input.json").read_text()), case)
            self.assertEqual(len((output / "results.jsonl").read_text().splitlines()), 24)
            with self.assertRaises(FileExistsError):
                run(cases, rubric, output)


if __name__ == "__main__":
    unittest.main()
