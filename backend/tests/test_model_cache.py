from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
from time import sleep
from types import SimpleNamespace
from unittest.mock import Mock, patch

import numpy as np
import pytest

from app.core.config import settings
from pipeline.rag import model_cache
from pipeline.rag.embedder import BgeM3Embedder
from pipeline.rag.reranker import TravelReranker
from pipeline.agents.tools.knowledge import TravelKnowledgeTool
from pipeline.agents.tools.registry import ToolRegistry
from pipeline.agents.validator import AgentValidator
from pipeline.agents.schemas import SubTask, ToolName


@pytest.fixture(autouse=True)
def isolated_models():
    with patch.dict(model_cache._resources, {}, clear=True), \
            patch.dict(model_cache._memory_failures, {}, clear=True):
        yield


def concurrent(factory, workers=6):
    barrier = Barrier(workers)
    def call(_):
        barrier.wait()
        return factory()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(call, range(workers)))


def test_embedding_loads_once_across_concurrent_instances():
    model = Mock()
    model.encode.return_value = np.zeros((1, settings.rag_vector_size))
    def load(*args, **kwargs):
        sleep(.02)
        return model
    with patch("pipeline.rag.embedder.SentenceTransformer", side_effect=load) as loader:
        instances = concurrent(BgeM3Embedder)
        assert loader.call_count == 1
        assert all(item.model is model for item in instances)
        assert len({id(item._inference_lock) for item in instances}) == 1
        assert len(instances[0].encode_query("Hue")) == settings.rag_vector_size


def test_reranker_loads_and_quantizes_once():
    with patch("pipeline.rag.reranker.CrossEncoder", return_value=Mock()) as loader, \
            patch("pipeline.rag.reranker.torch.cuda.is_available", return_value=False), \
            patch("pipeline.rag.reranker.torch.ao.quantization.quantize_dynamic") as quantize, \
            patch.object(settings, "rag_rerank_enabled", True), \
            patch.object(settings, "rag_reranker_cpu_int8", True):
        instances = concurrent(lambda: TravelReranker(retriever=Mock()))
        assert loader.call_count == quantize.call_count == 1
        assert len({id(item.model) for item in instances}) == 1
        assert len({id(item._inference_lock) for item in instances}) == 1


def test_lazy_knowledge_and_retriever_are_single_initialization():
    registry = ToolRegistry()
    with patch("pipeline.agents.tools.knowledge.TravelKnowledgeTool") as tool:
        instances = concurrent(lambda: registry.knowledge)
        assert tool.call_count == 1
        assert all(item is instances[0] for item in instances)
    knowledge = TravelKnowledgeTool()
    with patch("pipeline.agents.tools.knowledge.TravelReranker") as retriever:
        instances = concurrent(lambda: knowledge.retriever)
        assert retriever.call_count == 1
        assert all(item is instances[0] for item in instances)


def test_memory_failure_cooldown_then_successful_retry():
    key = ("test",)
    loader = Mock(side_effect=RuntimeError("unable to mmap: Cannot allocate memory (12)"))
    with patch.object(model_cache, "monotonic", return_value=100):
        def load():
            with pytest.raises(model_cache.ModelMemoryError):
                model_cache.get_model(key, loader)
        concurrent(load)
    assert loader.call_count == 1
    assert key not in model_cache._resources
    with patch.object(model_cache, "monotonic", return_value=161):
        resource = model_cache.get_model(key, lambda: "ready")
    assert resource.model == "ready"


def test_other_errors_do_not_poison_cache_and_keys_are_distinct():
    with pytest.raises(ValueError):
        model_cache.get_model(("a",), Mock(side_effect=ValueError("invalid config")))
    first = model_cache.get_model(("a",), object)
    assert model_cache.get_model(("a",), Mock()) is first
    assert model_cache.get_model(("b",), object) is not first
    assert not model_cache.is_memory_error(RuntimeError("connection failed"))


def test_memory_error_is_not_recoverable_in_workflow():
    observation = SimpleNamespace(data={"error_code": "RAG_MEMORY_ALLOCATION_FAILED"})
    validator = AgentValidator.__new__(AgentValidator)
    assert not validator._is_recoverable_tool_failure(observation)


def test_registry_reports_memory_failure_code():
    registry = ToolRegistry()
    task = SubTask(task_id="rag", description="Search", tool=ToolName.RAG)
    with patch.object(registry, "_execute_rag", side_effect=MemoryError("allocation failed")):
        observation = registry.execute(task)
    assert observation.data["error_code"] == "RAG_MEMORY_ALLOCATION_FAILED"


def test_shared_embedding_serializes_inference():
    active = peak = 0
    counter_lock = Lock()
    def encode(*args, **kwargs):
        nonlocal active, peak
        with counter_lock:
            active += 1
            peak = max(peak, active)
        sleep(.02)
        with counter_lock:
            active -= 1
        return np.zeros((1, settings.rag_vector_size))
    with patch("pipeline.rag.embedder.SentenceTransformer", return_value=Mock(encode=encode)):
        instances = [BgeM3Embedder() for _ in range(6)]
        barrier = Barrier(6)
        def query(item):
            barrier.wait()
            return item.encode_query("Hue")
        with ThreadPoolExecutor(max_workers=6) as pool:
            assert len(list(pool.map(query, instances))) == 6
    assert peak == 1
