from __future__ import annotations

import unittest
from unittest.mock import patch

from pipeline.rag.qdrant_store import TravelQdrantStore


class FlakyQdrantClient:
    def __init__(self, failures: int) -> None:
        self.failures = failures
        self.calls = 0

    def upsert(self, **kwargs) -> None:
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("temporary disconnect")


class QdrantIndexHardeningTest(unittest.TestCase):
    @staticmethod
    def _store(client: FlakyQdrantClient) -> TravelQdrantStore:
        store = TravelQdrantStore.__new__(TravelQdrantStore)
        store.client = client
        store.collection_name = "travel_chunks"
        return store

    @patch("pipeline.rag.qdrant_store.time.sleep")
    def test_upsert_retries_transient_failure(self, sleep) -> None:
        client = FlakyQdrantClient(failures=1)
        self._store(client).upsert([object()])
        self.assertEqual(client.calls, 2)
        sleep.assert_called_once_with(0.5)

    @patch("pipeline.rag.qdrant_store.time.sleep")
    def test_upsert_raises_after_three_attempts(self, sleep) -> None:
        client = FlakyQdrantClient(failures=3)
        with self.assertRaisesRegex(ConnectionError, "temporary disconnect"):
            self._store(client).upsert([object()])
        self.assertEqual(client.calls, 3)
        self.assertEqual(sleep.call_count, 2)


if __name__ == "__main__":
    unittest.main()
