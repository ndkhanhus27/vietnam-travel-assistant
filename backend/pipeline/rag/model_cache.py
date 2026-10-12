"""Process-local model resources; single initialization and bounded inference."""

from dataclasses import dataclass, field
from threading import Lock
from time import monotonic
from typing import Any, Callable


class ModelMemoryError(RuntimeError):
    pass


def is_memory_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return isinstance(exc, (MemoryError, ModelMemoryError)) or any(
        text in message for text in (
            "cannot allocate memory", "out of memory", "not enough memory",
            "defaultcpuallocator: can't allocate memory",
        )
    )


@dataclass
class ModelResource:
    model: Any
    inference_lock: Any = field(default_factory=Lock)


_resources: dict[tuple, ModelResource] = {}
_memory_failures: dict[tuple, float] = {}
_load_lock = Lock()
MEMORY_RETRY_SECONDS = 60


def get_model(key: tuple, factory: Callable[[], Any]) -> ModelResource:
    # Serialize cold loads, including different models, to limit peak memory.
    with _load_lock:
        if key in _resources:
            return _resources[key]
        retry_at = _memory_failures.get(key, 0)
        if monotonic() < retry_at:
            raise ModelMemoryError("Model loading paused after memory allocation failure; retry after 60 seconds.")
        try:
            resource = ModelResource(factory())
        except Exception as exc:
            if is_memory_error(exc):
                # Keep only the deadline, not a traceback retaining partial tensors.
                _memory_failures[key] = monotonic() + MEMORY_RETRY_SECONDS
                raise ModelMemoryError("Insufficient memory to load RAG model.") from None
            raise
        _resources[key] = resource
        _memory_failures.pop(key, None)
        return resource
