import pytest_asyncio

from app.ai.router import AIMessage, AIProvider
from app.api.analyst import get_analyst_provider


@pytest_asyncio.fixture
async def auth_headers(client):
    await client.post("/auth/register", json={"email": "op@example.com", "password": "supersecret1"})
    login = await client.post(
        "/auth/login", json={"email": "op@example.com", "password": "supersecret1"}
    )
    return {"Authorization": f"Bearer {login.json()['access_token']}"}


class FakeAI(AIProvider):
    name = "fake-ai"

    def __init__(self):
        self.last_context = None

    def available(self) -> bool:
        return True

    async def chat(self, messages: list[AIMessage], *, temperature: float = 0.2) -> str:
        self.last_context = messages[-1].content
        return "Summary: based on the indexed sources, one possible relationship is observed."


async def test_analyze_unavailable_without_ai(client, auth_headers):
    case = (await client.post("/investigations", json={"name": "C"}, headers=auth_headers)).json()
    # no AI configured by default -> 503
    r = await client.post(f"/investigations/{case['id']}/analyze", headers=auth_headers)
    assert r.status_code == 503
    assert r.json()["detail"] == "ai_unavailable"


async def test_analyze_with_fake_ai(client, auth_headers):
    fake = FakeAI()
    client.app.dependency_overrides[get_analyst_provider] = lambda: fake

    case = (await client.post("/investigations", json={"name": "Subject"}, headers=auth_headers)).json()
    cid = case["id"]
    await client.post(f"/investigations/{cid}/entities", json={"type": "phone", "value": "+250788123456"}, headers=auth_headers)
    await client.post(
        f"/investigations/{cid}/evidence",
        json={"type": "phone", "source_url": "https://example.com/contact"},
        headers=auth_headers,
    )

    r = await client.post(f"/investigations/{cid}/analyze", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["model"] == "fake-ai"
    assert "possible" in body["summary"].lower()
    assert body["evidence_counts"]["entities"] == 1
    # context handed to the model includes provenance
    assert "example.com/contact" in fake.last_context
