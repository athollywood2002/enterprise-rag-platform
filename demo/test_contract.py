import copy
import tempfile
import unittest
from pathlib import Path

from demo.contract import documents, validate_answer


class DemoContractTests(unittest.TestCase):
    def setUp(self):
        self.docs = documents(Path(__file__).parent / "fixtures")
        self.result = {
            "answer": "ORION [2] is the code; NetworkOps [1] owns it.",
            "generation": {"status": "complete"},
            "sources": [
                {"source": d["source"], "chunk": 0, "text": " ".join(d["text"].split())}
                for d in reversed(self.docs)
            ],
        }

    def test_csv_becomes_labeled_text(self):
        self.assertEqual(self.docs[1]["source"], "inventory.csv")
        self.assertIn("asset: demo-router-01; owner: NetworkOps", self.docs[1]["text"])

    def test_answer_and_reordered_citations(self):
        validate_answer(self.result, self.docs)

    def test_reject_missing_or_wrong_citations_and_tokens(self):
        for answer in [
            "ORION NetworkOps",
            "ORION [3] NetworkOps [1]",
            "ORION [1] NetworkOps [1]",
            "SCORPION [2] NetworkOps [1]",
        ]:
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                validate_answer({**self.result, "answer": answer}, self.docs)

    def test_reject_incomplete_generation(self):
        with self.assertRaises(ValueError):
            validate_answer({**self.result, "generation": {"status": "limit"}}, self.docs)

    def test_reject_wrong_source_text(self):
        result = copy.deepcopy(self.result)
        result["sources"][0]["text"] = "unrelated"
        with self.assertRaises(ValueError):
            validate_answer(result, self.docs)

    def test_quoted_csv_and_missing_cell(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "runbook.txt").write_text("Synthetic runbook")
            csv = root / "inventory.csv"
            csv.write_text('asset,owner,location\ndemo-router-01,NetworkOps,"Lab, west"\n')
            self.assertIn("location: Lab, west", documents(root)[1]["text"])
            csv.write_text("asset,owner,location\ndemo-router-01,NetworkOps\n")
            with self.assertRaises(ValueError):
                documents(root)


if __name__ == "__main__":
    unittest.main()
