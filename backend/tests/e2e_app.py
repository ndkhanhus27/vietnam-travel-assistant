"""Test-only API entry point: real auth/SQL/SSE with a deterministic assistant."""
import asyncio
from contextlib import asynccontextmanager
from app.api.dependencies import get_travel_workflow
from app.main import app
from app.db.session import close_db
from tests.test_api_regression import DeterministicWorkflow


class BrowserTestWorkflow(DeterministicWorkflow):
    async def stream(self, query, *, context=None):
        for stage in ("planning", "retrieving", "generating"):
            yield "progress", {"type": "stage", "stage": stage, "message": stage}
            await asyncio.sleep(0.4)
        state = await self.run(query, context=context)
        state["response"].answer = "## Lịch trình Huế\n\n" + "\n\n".join(
            f"Điểm {index}: **Khám phá Huế** cùng gia đình." for index in range(1, 25))
        yield "result", state


@asynccontextmanager
async def lifespan(app):
    app.state.redis = None
    yield
    await close_db()


app.router.lifespan_context = lifespan
app.dependency_overrides[get_travel_workflow] = lambda: BrowserTestWorkflow()
