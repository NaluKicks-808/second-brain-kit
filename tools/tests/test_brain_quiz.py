#!/usr/bin/env python3
"""Tests for tools/brain_quiz.py. No network, no model: stub commands and callables.
Run: python3 tools/tests/test_brain_quiz.py"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
import brain_quiz as bq  # noqa: E402

LEDGER = ("# L\n\n## Open\n\n| Trigger | Type | What to surface | Why it matters |\n|---|---|---|---|\n"
          "| 2026-10-01 | Date | **Other.** | w |\n\n## Done\n\n| Trigger | Type | What to surface | Why it matters |\n|---|---|---|---|\n")


def make_root(d, n=2):
    os.makedirs(os.path.join(d, "quiz"))
    os.makedirs(os.path.join(d, "wiki"))
    open(os.path.join(d, "wiki", "_reminders.md"), "w").write(LEDGER)
    open(os.path.join(d, "wiki", "a.md"), "w").write("---\nupdated: 2026-09-01\n---\nbody\n")
    qs = ["# comment line", ""]
    for i in range(n):
        qs.append(json.dumps({"id": "q%d" % i, "q": "Question %d?" % i, "gold": "G%d" % i,
                              "facts": ["f"], "cites": ["wiki/a.md"], "verified": "2026-01-01"}))
    open(os.path.join(d, "quiz", "questions.jsonl"), "w").write("\n".join(qs) + "\n")


def answerer(text="A", cites=("wiki/a.md",)):
    return lambda prompt: json.dumps({"answer": text, "cites": list(cites)})


def judger(verdicts, stale=False):
    def call(prompt):
        ids = [l.split('"')[3] for l in prompt.split("\n") if l.strip().startswith('"id":')]
        return "noise " + json.dumps({"results": [
            {"id": i, "verdict": verdicts[k % len(verdicts)], "stale_suspect": stale, "note": "n"}
            for k, i in enumerate(ids)]})
    return call


class Quiz(unittest.TestCase):
    def test_shipped_example_has_zero_questions(self):
        here = os.path.dirname(os.path.abspath(__file__))
        p = os.path.join(here, "..", "..", "quiz", "questions.example.jsonl")
        self.assertEqual(bq.load_questions(p), [])

    def test_loader_rejects_missing_field(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "q.jsonl")
            open(p, "w").write('{"id": "x"}\n')
            with self.assertRaises(ValueError):
                bq.load_questions(p)

    def test_scoring_and_artifacts(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 4)
            run = bq.run_quiz(d, answer_call=answerer(), judge_call=judger(["right", "partly", "wrong", "right"]),
                              today="2026-10-21", workers=1)
            self.assertEqual(run["score"], 62.5)
            self.assertEqual(run["gold_rechecks"], 4)      # a.md updated 2026-09-01 > verified 2026-01-01
            self.assertEqual(run["mean_pages"], 1.0)
            self.assertTrue(os.path.exists(os.path.join(d, "quiz", "runs", "2026-10-21.json")))
            self.assertIn("| 2026-10-21 | 62.5% |", open(os.path.join(d, "quiz", "trend.md")).read())

    def test_stale_suspect_clamped_by_cited_page_date(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 2)
            run = bq.run_quiz(d, answer_call=answerer(cites=("wiki/a.md",)), judge_call=judger(["wrong"], stale=True),
                              today="2026-10-21", workers=1)
            self.assertEqual(run["stale_suspects"], 2)
            run = bq.run_quiz(d, answer_call=answerer(cites=()), judge_call=judger(["wrong"], stale=True),
                              today="2026-10-22", workers=1)
            self.assertEqual(run["stale_suspects"], 0)    # no newer cited page, no suspect

    def test_failed_answer_scores_zero_and_judge_failure_does_not_crash(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 2)

            def boom(prompt):
                raise RuntimeError("no model")
            run = bq.run_quiz(d, answer_call=boom, judge_call=boom, today="2026-10-21", workers=1)
            self.assertIn("call failed", run["results"][0]["note"])

    def test_judge_failure_aborts_without_writing(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 2)

            def boom(prompt):
                raise RuntimeError("expired login")
            before = open(os.path.join(d, "wiki", "_reminders.md")).read()
            run = bq.run_quiz(d, answer_call=answerer(), judge_call=boom, today="2026-10-21",
                              workers=1, file_ledger_row=True)
            self.assertIsNone(run["score"])
            self.assertIn("expired login", run["aborted"])
            self.assertFalse(os.path.exists(os.path.join(d, "quiz", "runs")))
            self.assertFalse(os.path.exists(os.path.join(d, "quiz", "trend.md")))
            self.assertEqual(open(os.path.join(d, "wiki", "_reminders.md")).read(), before)
            empty = bq.run_quiz(d, answer_call=answerer(), judge_call=lambda p: "no json here",
                                today="2026-10-21", workers=1)
            self.assertIn("no verdicts", empty["aborted"])

    def test_partial_run_is_never_the_baseline(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 2)
            bq.run_quiz(d, answer_call=answerer(), judge_call=judger(["right"]), today="2026-10-20",
                        only="q0", workers=1)
            self.assertTrue(os.path.exists(os.path.join(d, "quiz", "runs", "2026-10-20.partial.json")))
            self.assertFalse(os.path.exists(os.path.join(d, "quiz", "trend.md")))
            run = bq.run_quiz(d, answer_call=answerer(), judge_call=judger(["right", "partly"]),
                              today="2026-10-21", workers=1)
            self.assertIsNone(run["previous_score"])
            self.assertEqual(run["threshold"], "")

    def test_hand_written_quiz_row_is_never_overwritten(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 1)
            p = os.path.join(d, "wiki", "_reminders.md")
            mine = "| 2026-11-01 | Date | **Add Brain quiz questions for the new project** | w |"
            open(p, "w").write(LEDGER.replace("| 2026-10-01 | Date | **Other.** | w |", mine))
            run = bq.run_quiz(d, answer_call=answerer(), judge_call=judger(["wrong"]), today="2026-10-21",
                              workers=1, file_ledger_row=True)
            self.assertEqual(run["ledger"], "filed")
            text = open(p).read()
            self.assertIn(mine, text)
            self.assertEqual(text.count("Brain quiz fell"), 1)

    def test_plain_text_answer_accepted(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 1)
            run = bq.run_quiz(d, answer_call=lambda p: "just text", judge_call=judger(["right"]),
                              today="2026-10-21")
            self.assertEqual(run["results"][0]["answer"], "just text")
            self.assertEqual(run["results"][0]["cites"], [])

    def test_threshold_row_filed_then_bumped_never_duplicated(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 2)
            bad = dict(answer_call=answerer(), judge_call=judger(["wrong"]), workers=1, file_ledger_row=True)
            r1 = bq.run_quiz(d, today="2026-10-21", **bad)
            r2 = bq.run_quiz(d, today="2026-10-22", **bad)
            self.assertEqual((r1["ledger"], r2["ledger"]), ("filed", "bumped"))
            text = open(os.path.join(d, "wiki", "_reminders.md")).read()
            self.assertEqual(text.count("Brain quiz fell"), 1)
            self.assertLess(text.index("Brain quiz fell"), text.index("## Done"))
            self.assertIn("2026-10-22", text.split("Brain quiz fell")[0].split("\n")[-1])

    def test_drop_against_previous_and_partial_never_alarms(self):
        self.assertEqual(bq.breach(90.0, 95.0), "")
        self.assertIn("fell", bq.breach(80.0, 92.0))
        self.assertIn("under", bq.breach(70.0, None))
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 3)
            run = bq.run_quiz(d, answer_call=answerer(), judge_call=judger(["wrong"]), today="2026-10-21",
                              limit=1, workers=1, file_ledger_row=True)
            self.assertEqual(run["threshold"], "")
            self.assertNotIn("ledger", run)

    def test_command_caller_end_to_end_with_stub_script(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 2)
            stub = os.path.join(d, "stub.py")
            open(stub, "w").write(
                "import sys, json, re\n"
                "p = sys.stdin.read()\n"
                "if 'ITEMS:' in p:\n"
                "    ids = re.findall(r'\"id\": \"([^\"]+)\"', p)\n"
                "    print(json.dumps({'results': [{'id': i, 'verdict': 'right', 'stale_suspect': False} for i in ids]}))\n"
                "else:\n"
                "    print(json.dumps({'answer': 'stub', 'cites': ['wiki/a.md']}))\n")
            cmd = "%s %s" % (sys.executable, stub)
            out = io.StringIO()
            with redirect_stdout(out):
                code = bq.main(["--root", d, "--answer-cmd", cmd, "--judge-cmd", cmd, "--workers", "1"])
            self.assertEqual(code, 0)
            self.assertIn("100.0%", out.getvalue())

    def test_dry_run_calls_nothing_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            make_root(d, 2)
            out = io.StringIO()
            with redirect_stdout(out):
                code = bq.main(["--root", d, "--dry-run", "--answer-cmd", "/nonexistent/cmd"])
            self.assertEqual(code, 0)
            self.assertIn("DRY: 2 questions", out.getvalue())
            self.assertFalse(os.path.exists(os.path.join(d, "quiz", "runs")))

    def test_missing_questions_file_message(self):
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            with redirect_stdout(out):
                self.assertEqual(bq.main(["--root", d]), 1)
            self.assertIn("questions.example.jsonl", out.getvalue())


if __name__ == "__main__":
    unittest.main()
