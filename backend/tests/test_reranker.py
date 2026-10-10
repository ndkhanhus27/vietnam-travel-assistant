from __future__ import annotations

import unittest
import torch
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.core.config import settings
from pipeline.rag.reranker import TravelReranker
from pipeline.agents.tools.knowledge import TravelKnowledgeTool


def candidate(point_id):
    return SimpleNamespace(point_id=point_id, hybrid_score=.03, dense_rank=1, dense_score=.8,
        bm25_rank=2, bm25_score=3, entity_rank=None, document_id="doc", chunk_index=0,
        title="Title", content="Content", source_name="Source", source_url="https://example.com",
        entities=[], entity_types=[], primary_entities=[])


class RerankerTests(unittest.TestCase):
    def setUp(self):
        self.reranker = TravelReranker.__new__(TravelReranker)
        self.reranker.model = Mock()
        self.points = [candidate(str(index)) for index in range(4)]

    def test_cross_encoder_legacy_mode(self):
        self.reranker.model.predict.return_value = [0, 3, 2, 1]
        rows = self.reranker.rerank(query="query", candidates=self.points, limit=2)
        self.assertEqual([row.point_id for row in rows], ["1", "2"])
        self.assertEqual(rows[0].rerank_score, 3)
        self.assertEqual(rows[0].cross_encoder_score, 3)
        self.assertEqual(rows[0].hybrid_rank, 2)

    def test_scores_follow_final_order_and_preserve_raw_score(self):
        self.reranker.model.predict.return_value = [0, 3, 2, 1]
        rows = self.reranker.rerank(query="query", candidates=self.points, limit=4)
        self.assertEqual([row.point_id for row in rows], ["1", "2", "3", "0"])
        self.assertEqual([row.rerank_score for row in rows], sorted([row.rerank_score for row in rows], reverse=True))
        self.assertEqual(rows[-1].cross_encoder_score, 0)
        self.assertEqual([row.rerank_rank for row in rows], [1, 2, 3, 4])

    def test_empty_query_candidates_and_nonpositive_limit_skip_inference(self):
        for query, points, limit in ((" ", self.points, 2), ("q", [], 2), ("q", self.points, 0), ("q", self.points, -1)):
            self.assertEqual(self.reranker.rerank(query=query, candidates=points, limit=limit), [])
        self.reranker.model.predict.assert_not_called()

    def test_score_count_and_nonfinite_scores_are_rejected(self):
        for scores in ([1], [0, 1, float("nan"), 2], [0, 1, float("inf"), 2]):
            self.reranker.model.predict.return_value = scores
            with self.assertRaises(RuntimeError):
                self.reranker.rerank(query="q", candidates=self.points)

    def test_cpu_int8_quantizes_linear_layers_without_loading_weights(self):
        encoder = SimpleNamespace(model=torch.nn.Sequential(torch.nn.Linear(3, 1)).eval())
        with patch("pipeline.rag.reranker.CrossEncoder", return_value=encoder), \
                patch("pipeline.rag.reranker.torch.cuda.is_available", return_value=False), \
                patch.object(settings, "rag_reranker_cpu_int8", True):
            reranker = TravelReranker(retriever=SimpleNamespace())
        self.assertIsInstance(reranker.model.model[0], torch.ao.nn.quantized.dynamic.Linear)
        self.assertTrue(torch.isfinite(reranker.model.model(torch.ones(1, 3))).all())

    def test_disabled_reranker_skips_model_and_preserves_hybrid_order(self):
        hybrid = Mock()
        hybrid.search.return_value = self.points
        with patch("pipeline.rag.reranker.CrossEncoder") as encoder, \
                patch.object(settings, "rag_rerank_enabled", False):
            reranker = TravelReranker(retriever=hybrid)
        encoder.assert_not_called()
        rows = reranker.search("query", limit=3)
        hybrid.search.assert_called_once_with("query", limit=3)
        self.assertEqual([row.point_id for row in rows], ["0", "1", "2"])
        self.assertTrue(all(row.cross_encoder_score is None for row in rows))
        self.assertTrue(all(row.rerank_score == row.hybrid_score for row in rows))

    def test_evidence_keeps_final_rank_score_and_raw_model_score(self):
        self.reranker.model.predict.return_value = [0, 3, 2, 1]
        chunk = self.reranker.rerank(query="q", candidates=self.points, limit=1)[0]
        evidence = TravelKnowledgeTool._to_evidence(chunk=chunk, entity=None)
        self.assertEqual(evidence.score, chunk.rerank_score)
        self.assertEqual(evidence.metadata["cross_encoder_score"], chunk.cross_encoder_score)
