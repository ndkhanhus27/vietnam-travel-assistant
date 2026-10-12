from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from pipeline.agents.planner import TravelPlanner


QUERY = "Lên lịch Huế 3 ngày cuối tuần này, xem có mưa không, có sự kiện gì và từ Đại Nội đến lăng Khải Định đi mất bao lâu?"


async def main(run: bool) -> None:
    if run:
        from pipeline.agents.workflow import build_workflow
        state = await build_workflow().run(QUERY)
        payload = {key: value.model_dump(mode="json") if hasattr(value, "model_dump") else
                   [item.model_dump(mode="json") for item in value]
                   for key, value in state.items()
                   if key in {"plan", "observations", "validation", "reasoner_output", "response"}}
    else:
        payload = {"plan": TravelPlanner().plan(QUERY).model_dump(mode="json")}
    path = Path(__file__).resolve().parents[2] / ".cache" / "compound-query-smoke.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload["plan"], ensure_ascii=False, indent=2))
    if run:
        print(json.dumps(payload["validation"], ensure_ascii=False, indent=2))
        print(payload["response"]["answer"])
    print(f"Trace: {path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", action="store_true")
    asyncio.run(main(parser.parse_args().run))
