"""Opt-in HTTP smoke test using an operator-supplied test account."""
import asyncio
import os
import httpx


async def main():
    origin = os.environ["SMOKE_BASE_URL"].rstrip("/")
    email = os.environ["SMOKE_EMAIL"]
    password = os.environ["SMOKE_PASSWORD"]
    conversation_id = None
    refresh = None
    async with httpx.AsyncClient(base_url=origin, timeout=300, follow_redirects=True) as client:
        health = await client.get("/health")
        health.raise_for_status()
        assert health.json()["status"] == "ok", "Health is not OK"
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": password})
        login.raise_for_status()
        auth = login.json()
        refresh = auth["refresh_token"]
        client.headers["Authorization"] = f"Bearer {auth['access_token']}"
        try:
            created = await client.post("/api/v1/conversations", json={})
            created.raise_for_status()
            conversation_id = created.json()["id"]
            question = "Ga Đà Lạt có gì đặc biệt?"
            result = await client.post(f"/api/v1/conversations/{conversation_id}/messages", json={"content": question})
            result.raise_for_status()
            messages = await client.get(f"/api/v1/conversations/{conversation_id}/messages")
            messages.raise_for_status()
            history = messages.json()
            assert any(item["role"] == "user" and item["content"] == question for item in history), "Question was not persisted"
            answers = [item for item in history if item["role"] == "assistant" and item["content"].strip()]
            assert answers, "Assistant answer is missing"
            assert answers[-1].get("citations"), "RAG answer has no citations"
            assert not answers[-1].get("warnings"), "Answer is degraded; inspect provider/model logs"
            print("PASS: health, login, real RAG answer, citations, persisted question and answer")
        finally:
            if conversation_id:
                deleted = await client.delete(f"/api/v1/conversations/{conversation_id}")
                deleted.raise_for_status()
            if refresh:
                logged_out = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh})
                logged_out.raise_for_status()


if __name__ == "__main__":
    asyncio.run(main())
