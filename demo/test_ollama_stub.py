"""Protocol-only regressions; these do not evaluate generated answer correctness."""

import json
import unittest

from demo.ollama_stub import request_excerpts


class EnvelopeTests(unittest.TestCase):
    def test_managed_records_use_user_message_and_preserve_source_ids(self):
        records = [
            {
                "citation": 2,
                "source": "book.xlsx",
                "location": "Sheet A · row 9",
                "text": "RTO hours: 2\n[1] text inside source",
            },
            {"citation": 4, "source": "book.xlsx", "text": "RPO minutes: 0"},
        ]
        question, excerpts = request_excerpts(
            [
                {"role": "system", "content": "Instructions without excerpts"},
                {
                    "role": "user",
                    "content": json.dumps({"question": "Compare", "evidence": records}),
                },
            ]
        )
        self.assertEqual(question, "Compare")
        self.assertEqual(
            excerpts,
            [
                ("2", "book.xlsx", "Sheet A · row 9", records[0]["text"]),
                ("4", "book.xlsx", None, "RPO minutes: 0"),
            ],
        )

    def test_legacy_envelope_is_still_supported(self):
        prompt = "Excerpts:\n[1] a.txt (page None, chunk 0): ORION\n\n[2] b.csv (page None, chunk 0): NetworkOps\n\nQuestion: Who?"
        question, excerpts = request_excerpts([{"role": "user", "content": prompt}])
        self.assertEqual(question, prompt)
        self.assertEqual([r[0] for r in excerpts], ["1", "2"])
        self.assertEqual([r[3] for r in excerpts], ["ORION", "NetworkOps"])
