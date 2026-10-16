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

    def test_accepts_documents_only_v2(self) -> None:
        bundle = self._bundle()
        del bundle["entity_candidates"]
        self.assertIs(validate_bundle(bundle), bundle)

    def test_legacy_entities_are_ignored(self) -> None:
        bundle = self._bundle()
        bundle["format_version"] = 1
        bundle["entity_candidates"][0]["document_id"] = str(uuid.uuid4())
        self.assertIs(validate_bundle(bundle), bundle)

    def test_rejects_unknown_version(self) -> None:
        bundle = self._bundle()
        bundle["format_version"] = 99
        with self.assertRaisesRegex(ValueError, "format_version"):
            validate_bundle(bundle)

    def test_rejects_duplicate_document_ids(self) -> None:
        bundle = self._bundle()
        bundle["documents"].append(dict(bundle["documents"][0]))
        with self.assertRaisesRegex(ValueError, "duplicate IDs"):
            validate_bundle(bundle)


if __name__ == "__main__":
    unittest.main()
