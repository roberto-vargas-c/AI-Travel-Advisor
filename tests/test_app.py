"""Offline tests: run with ATLAS_MOCK=1 (no API key, no network needed)."""
import os

os.environ["ATLAS_MOCK"] = "1"
os.environ["DATA_DIR"] = "/tmp/atlas-test-data"

from fastapi.testclient import TestClient  # noqa: E402

from app import agent, config, prompts, security  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)


def new_session():
    r = client.post("/api/session")
    assert r.status_code == 200
    return r.json()["session_id"]


def test_full_flow_plan_and_image():
    sid = new_session()
    r = client.post("/api/chat", json={"session_id": sid, "message": "I want to go to Kyoto"})
    assert r.status_code == 200 and r.json()["plan"] is None
    r = client.post("/api/chat", json={"session_id": sid, "message": "3 days, food, temples and hiking"})
    body = r.json()
    plan = body["plan"]
    assert plan and len(plan["days"]) == 3
    assert plan["budget"]["total"] == sum(i["amount"] for i in plan["budget"]["items"])
    assert body["usage"]["cost_usd"] > 0
    img = client.post("/api/illustrate", json={"session_id": sid, "plan_id": plan["id"]}).json()["image"]
    assert client.get(img).headers["content-type"] == "image/png"
    md = client.get(f"/api/plan/{sid}/{plan['id']}.md")
    assert md.status_code == 200 and "Day 1" in md.text


def test_memory_is_kept():
    sid = new_session()
    client.post("/api/chat", json={"session_id": sid, "message": "Kyoto please"})
    s = agent_session(sid)
    assert [m["role"] for m in s.history] == ["assistant", "user", "assistant"]


def agent_session(sid):
    from app.main import SESSIONS
    return SESSIONS[sid]


def test_input_guards():
    sid = new_session()
    assert client.post("/api/chat", json={"session_id": sid, "message": "x" * 5000}).status_code == 400
    assert client.post("/api/chat", json={"session_id": sid, "message": "   "}).status_code == 400
    assert client.post("/api/chat", json={"session_id": "nope", "message": "hi"}).status_code == 404
    r = client.post("/api/chat", json={"session_id": sid, "message": "FLAGME"})
    assert "can't help" in r.json()["reply"]


def test_path_traversal_blocked():
    assert client.get("/api/images/..%2F..%2Fetc%2Fpasswd").status_code == 404
    assert client.get("/api/images/abc.png").status_code == 404


def test_itinerary_validation():
    s = agent.Session()
    res, pid = s._create_itinerary({"destination": "Rome", "duration_days": 60})
    assert "error" in res and pid is None
    res, pid = s._create_itinerary({"destination": "Rome", "duration_days": 3, "start_date": "2001-01-01"})
    assert "past" in res["error"]


def test_canary_leak_detected():
    assert security.leaked(f"sure: {prompts.CANARY}")


def test_summarisation_compacts_history():
    old = config.SUMMARY_TRIGGER_TOKENS
    config.SUMMARY_TRIGGER_TOKENS = 200
    try:
        s = agent.Session()
        for _ in range(4):
            s.history += [{"role": "user", "content": "word " * 120}, {"role": "assistant", "content": "ok"}]
        s._maybe_summarise()
        assert s.summary and s.history[0]["role"] == "user"
        assert len(s.history) <= config.SUMMARY_KEEP_MESSAGES
    finally:
        config.SUMMARY_TRIGGER_TOKENS = old


def test_rate_limit():
    lim = security.RateLimiter(2, 60)
    assert lim.allow("a") and lim.allow("a") and not lim.allow("a")
