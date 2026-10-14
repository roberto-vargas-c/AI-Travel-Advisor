"""HTTP API + static chat UI."""
import logging
import os
import re
import threading
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import config, prompts, security
from .agent import AgentError, Session, plan_to_markdown
from .usage import DAILY

log = logging.getLogger("atlas")
STATIC = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(title="Atlas travel advisor", docs_url=None, redoc_url=None)
SESSIONS: dict[str, Session] = {}
_sessions_lock = threading.Lock()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; img-src 'self' data: blob:; "
        # 'unsafe-inline' styles are needed by the "Save as image" renderer; scripts stay strict.
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com data:; "
        "script-src 'self' https://cdn.jsdelivr.net; "
        "connect-src 'self' https://fonts.googleapis.com https://fonts.gstatic.com")
    return response


def client_ip(request: Request):
    fwd = request.headers.get("x-forwarded-for")
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")


def get_session(sid) -> Session:
    s = SESSIONS.get(sid or "")
    if not s:
        raise HTTPException(404, "This conversation has expired. Start a new trip.")
    s.last_seen = time.time()
    return s


def _gc_sessions():
    now = time.time()
    with _sessions_lock:
        for sid in [k for k, s in SESSIONS.items() if now - s.last_seen > config.SESSION_TTL_SECONDS]:
            SESSIONS.pop(sid, None)
        while len(SESSIONS) >= config.MAX_SESSIONS:
            SESSIONS.pop(min(SESSIONS, key=lambda k: SESSIONS[k].last_seen))


def _public(session):
    return {"usage": session.usage.summary()}


class ChatIn(BaseModel):
    session_id: str
    message: str


class ImageIn(BaseModel):
    session_id: str
    plan_id: str


@app.get("/healthz")
def health():
    return {"ok": True, "mock": config.MOCK}


@app.get("/api/config")
def public_config():
    return {"chat_model": config.CHAT_MODEL, "planner_model": config.PLANNER_MODEL,
            "image_model": config.IMAGE_MODEL, "max_input_chars": config.MAX_INPUT_CHARS,
            "mock": config.MOCK}


@app.post("/api/session")
def new_session(request: Request):
    if not security.session_limiter.allow(client_ip(request)):
        raise HTTPException(429, "Too many new trips from this network. Try again in a while.")
    _gc_sessions()
    s = Session()
    with _sessions_lock:
        SESSIONS[s.id] = s
    return {"session_id": s.id, "greeting": prompts.GREETING, **_public(s)}


@app.post("/api/chat")
def chat(body: ChatIn, request: Request):
    if not security.message_limiter.allow(client_ip(request)):
        raise HTTPException(429, "You're sending messages quickly. Wait a moment and try again.")
    if DAILY.exhausted():
        raise HTTPException(503, "Atlas has reached today's usage limit. Try again tomorrow.")
    s = get_session(body.session_id)
    text, err = security.clean_input(body.message)
    if err:
        raise HTTPException(400, err)
    if not s.lock.acquire(timeout=1):
        raise HTTPException(409, "Atlas is still answering your last message.")
    try:
        result = s.chat(text)
    except AgentError as e:
        raise HTTPException(400, str(e))
    except Exception:
        log.exception("chat failed")
        raise HTTPException(502, "Atlas couldn't reach the AI service. Send your message again.")
    finally:
        s.lock.release()
    plan = s.plans.get(result["plan_id"]) if result["plan_id"] else None
    return {"reply": result["reply"], "plan": plan, **_public(s)}


@app.post("/api/illustrate")
def illustrate(body: ImageIn):
    if DAILY.exhausted():
        raise HTTPException(503, "Atlas has reached today's usage limit.")
    s = get_session(body.session_id)
    try:
        url = s.illustrate(body.plan_id)
    except AgentError as e:
        raise HTTPException(400, str(e))
    except Exception:
        log.exception("image failed")
        raise HTTPException(502, "The illustration couldn't be created this time.")
    return {"image": url, **_public(s)}


@app.get("/api/images/{name}")
def image(name: str):
    if not re.fullmatch(r"[A-Za-z0-9_-]{10,40}\.png", name):    # no path traversal
        raise HTTPException(404)
    path = os.path.join(config.DATA_DIR, name)
    if not os.path.exists(path):
        raise HTTPException(404)
    return FileResponse(path, media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})


@app.get("/api/plan/{session_id}/{plan_id}.md")
def plan_markdown(session_id: str, plan_id: str):
    s = get_session(session_id)
    plan = s.plans.get(plan_id) or {}
    if not plan:
        raise HTTPException(404)
    slug = re.sub(r"[^a-z0-9]+", "-", plan["title"].lower()).strip("-")[:60] or "trip"
    return PlainTextResponse(plan_to_markdown(plan), media_type="text/markdown",
                             headers={"Content-Disposition": f'attachment; filename="{slug}.md"'})


@app.exception_handler(HTTPException)
def http_error(request, exc: HTTPException):
    return JSONResponse({"error": exc.detail or "Not found"}, status_code=exc.status_code)


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


app.mount("/static", StaticFiles(directory=STATIC), name="static")
