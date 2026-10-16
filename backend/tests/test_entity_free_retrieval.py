from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct, VectorParams, Distance

from pipeline.agents.tools.knowledge import TravelKnowledgeTool
from pipeline.agents.schemas import EvidenceItem, EvidenceSource
from pipeline.rag.bm25_index import QdrantBm25Index
from pipeline.rag.hybrid_retriever import HybridRetriever
from scripts.copy_entity_free_index import clean_payload, copy_index


class EntityFreeRetrievalTests(unittest.TestCase):
    def test_bm25_ignores_legacy_entities(self):
        self.assertEqual(QdrantBm25Index._build_lexical_text({
            "title": "Hue", "content": "Heritage", "entities": ["Da Lat"],
            "primary_entities": ["Sai Gon"],
        }), "Hue\nHue\nHeritage")

    def test_fusion_has_only_dense_and_bm25(self):
        retriever = HybridRetriever.__new__(HybridRetriever)
        retriever.dense = Mock()
        retriever.bm25 = Mock()
        payload = {"title": "Hue", "content": "Heritage", "primary_entities": ["Da Lat"]}
        retriever.dense.search.return_value = [SimpleNamespace(point_id="a", score=.9, payload=payload)]
        retriever.bm25.search.return_value = [SimpleNamespace(point_id="a", rank=1, score=3, payload=payload)]
        rows = retriever.search("Da Lat")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].hybrid_score, retriever._rrf(rank=1, weight=1) * 2)
        retriever.bm25.payload_by_id.assert_not_called()

    def test_coverage_ignores_old_metadata_and_incidental_mentions(self):
        chunk = SimpleNamespace(title="Other", content="Hue is mentioned once", primary_entities=["Hue"])
        matches = lambda: TravelKnowledgeTool._chunk_matches_entity(entity="Hue", chunk=chunk)
        self.assertFalse(matches())
        chunk.title = "Travel to Hue"
        self.assertTrue(matches())
        chunk.title = "Other"
        chunk.content = "Hue has heritage. Visit Hue for food."
        self.assertTrue(matches())
        chunk.content = "Huex Huex"
        self.assertFalse(matches())

    def test_clean_payload_preserves_provenance(self):
        self.assertEqual(clean_payload({"document_id": "x", "source_url": "url", "entities": []}),
                         {"document_id": "x", "source_url": "url"})

    def test_comparison_falls_back_only_for_the_missing_place(self):
        web = Mock()
        web.search.return_value = [EvidenceItem(
            evidence_id="web_other", source_type=EvidenceSource.WEB,
            title="Da Lat", content="Travel information", entity="Da Lat",
        )]
        tool = TravelKnowledgeTool(web_tool=web)
        chunk = SimpleNamespace(
            point_id="hue", document_id="doc", chunk_index=0,
            title="Hue", content="Heritage", source_url="https://example.com/hue",
            source_name="Guide", rerank_score=1., hybrid_score=.02,
            cross_encoder_score=1.,
        )
        tool._retriever = Mock()
        tool._retriever.search.return_value = [chunk]
        result = tool.search(task_id="comparison", query="Compare Hue and Da Lat",
                             entities=["Hue", "Da Lat"], require_all_entities=True)
        self.assertTrue(result.coverage.sufficient)
        self.assertEqual(result.data["rag_covered_entities"], ["Hue"])
        self.assertEqual(result.data["rag_missing_entities"], ["Da Lat"])
        self.assertEqual(result.data["web_covered_entities"], ["Da Lat"])
        web.search.assert_called_once()
        self.assertEqual(web.search.call_args.kwargs["entity"], "Da Lat")

    def test_missing_place_is_not_marked_covered_when_web_has_no_evidence(self):
        web = Mock()
        web.search.return_value = []
        tool = TravelKnowledgeTool(web_tool=web)
        tool._retriever = Mock()
        tool._retriever.search.return_value = []
        result = tool.search(task_id="missing", query="Visit Da Lat", entities=["Da Lat"])
        self.assertFalse(result.coverage.sufficient)
        self.assertEqual(result.coverage.missing_entities, ["Da Lat"])

    def test_copy_preserves_ids_vectors_and_source(self):
        client = QdrantClient(":memory:")
        self.addCleanup(client.close)
        client.create_collection("old", vectors_config=VectorParams(size=2, distance=Distance.COSINE))
        client.upsert("old", points=[PointStruct(id=1, vector=[1., 0.], payload={"title": "Hue", "entities": ["Hue"]})])
        self.assertEqual(copy_index(client, "old", "new"), 1)
        old = client.retrieve("old", [1], with_vectors=True)[0]
        new = client.retrieve("new", [1], with_vectors=True)[0]
        self.assertEqual(old.vector, new.vector)
        self.assertEqual(new.payload, {"title": "Hue"})
        self.assertIn("entities", old.payload)
        with self.assertRaises(ValueError):
            copy_index(client, "old", "new")
        with self.assertRaises(ValueError):
            copy_index(client, "old", "old")
