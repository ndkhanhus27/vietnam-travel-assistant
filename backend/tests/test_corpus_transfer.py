from __future__ import annotations

import unittest
import uuid

from scripts.corpus_transfer import FORMAT_VERSION, validate_bundle


class CorpusTransferValidationTest(unittest.TestCase):
    def _bundle(self) -> dict:
        document_id = str(uuid.uuid4())
        return {
            "format_version": FORMAT_VERSION,
            "documents": [{"id": document_id}],
            "entity_candidates": [
                {
                    "id": str(uuid.uuid4()),
                    "document_id": document_id,
                }
            ],
        }

    def test_accepts_matching_document_reference(self) -> None:
        bundle = self._bundle()
        self.assertIs(validate_bundle(bundle), bundle)

    def test_rejects_candidate_with_missing_document(self) -> None:
        bundle = self._bundle()
        bundle["entity_candidates"][0]["document_id"] = str(uuid.uuid4())
        with self.assertRaisesRegex(ValueError, "missing document"):
            validate_bundle(bundle)

    def test_rejects_duplicate_document_ids(self) -> None:
        bundle = self._bundle()
        bundle["documents"].append(dict(bundle["documents"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate IDs"):
            validate_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
