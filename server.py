"""
FastAPI backend — wraps K8sAgent and exposes a REST API for the React frontend.
"""
import asyncio
import json
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from config.settings import settings
from k8s.client import K8sClient
from k8s.operations import K8sOperations
from agent.factory import create_agent
from agent.confirmation import ConfirmationRequired
from inspector.inspector import Inspector
from kb.case_store import init_db, search_cases, format_cases_for_context, save_case
from kb.extractor import extract_case, should_extract
from utils.logger import get_logger

logger = get_logger(__name__)

_sessions: dict = {}
_pending: dict = {}   # session_id → {tool_name, tool_input, tool_id, description, assistant_msg}
_inspector: Inspector | None = None


# ------------------------------------------------------------------ #
# KB background helpers
# ------------------------------------------------------------------ #

def _bg_extract(history_snapshot: list, last_reply: str) -> None:
    """Save a fault case if the conversation contains a root-cause conclusion."""
    try:
        if not should_extract(history_snapshot, last_reply):
            return
        case = extract_case(history_snapshot)
        if case:
            cid = save_case(
                symptom=case.get('symptom', ''),
                root_cause=case.get('root_cause', ''),
                solution=case.get('solution', ''),
                resource_kind=case.get('resource_kind', ''),
                resource_name=case.get('resource_name', ''),
                namespace=case.get('namespace', ''),
            )
            logger.info(f"KB: saved case #{cid} — {case.get('symptom','')[:60]}")
    except Exception as exc:
        logger.error(f"KB extraction error: {exc}")


def _bg_extract_on_reset(history_snapshot: list) -> None:
    """Triggered on session reset — extract without the heuristic keyword gate."""
    if len(history_snapshot) < 6:
        return
    try:
        case = extract_case(history_snapshot)
        if case:
            cid = save_case(
                symptom=case.get('symptom', ''),
                root_cause=case.get('root_cause', ''),
                solution=case.get('solution', ''),
                resource_kind=case.get('resource_kind', ''),
                resource_name=case.get('resource_name', ''),
                namespace=case.get('namespace', ''),
            )
            logger.info(f"KB (reset): saved case #{cid} — {case.get('symptom','')[:60]}")
    except Exception as exc:
        logger.error(f"KB extraction (reset) error: {exc}")


def _spawn_extract(history_snapshot: list, last_reply: str) -> None:
    threading.Thread(target=_bg_extract, args=(history_snapshot, last_reply), daemon=True).start()


def _spawn_extract_on_reset(history_snapshot: list) -> None:
    threading.Thread(target=_bg_extract_on_reset, args=(history_snapshot,), daemon=True).start()


# ------------------------------------------------------------------ #
# Lifespan — start/stop background inspector, init DB
# ------------------------------------------------------------------ #

@asynccontextmanager
async def lifespan(app: FastAPI):
    global _inspector

    # Always initialise KB (creates tables if absent)
    try:
        init_db()
        logger.info("KB: database ready")
    except Exception as e:
        logger.error(f"KB init failed: {e}")

    _inspector_task = None
    if settings.inspector_enabled:
        try:
            client = K8sClient(kubeconfig=settings.kubeconfig, namespace=settings.k8s_namespace)
            client.connect()
            ops = K8sOperations(client)
            agent = create_agent(ops)
            _inspector = Inspector(
                ops=ops,
                agent=agent,
                interval=settings.inspector_interval,
                cooldown_minutes=settings.inspector_cooldown_minutes,
                restart_threshold=settings.inspector_restart_threshold,
            )
            _inspector_task = asyncio.create_task(_inspector.start())
            logger.info("Inspector started")
        except Exception as e:
            logger.error(f"Inspector init failed (K8s unavailable?): {e}")
    yield
    if _inspector:
        _inspector.stop()
    if _inspector_task:
        _inspector_task.cancel()
        try:
            await asyncio.wait_for(_inspector_task, timeout=3)
        except (asyncio.CancelledError, asyncio.TimeoutError):
            pass


app = FastAPI(title="K8s Ops Agent API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_agent(session_id: str):
    if session_id not in _sessions:
        client = K8sClient(kubeconfig=settings.kubeconfig, namespace=settings.k8s_namespace)
        client.connect()
        ops = K8sOperations(client)
        _sessions[session_id] = create_agent(ops)
    return _sessions[session_id]


# ------------------------------------------------------------------ #
# Schemas
# ------------------------------------------------------------------ #

class ChatRequest(BaseModel):
    message: str
    session_id: str

class ChatResponse(BaseModel):
    reply: str
    session_id: str
    pending_action: dict[str, Any] | None = None

class ConfirmRequest(BaseModel):
    session_id: str
    confirmed: bool


# ------------------------------------------------------------------ #
# Routes
# ------------------------------------------------------------------ #

@app.get("/api/health")
def health():
    return {"status": "ok", "provider": settings.llm_provider}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    # Block new messages while a confirmation is pending (prevents history corruption)
    if req.session_id in _pending:
        desc = _pending[req.session_id]["description"]
        return ChatResponse(
            reply="⚠️ 有待确认的危险操作，请先处理后再发送新消息。",
            session_id=req.session_id,
            pending_action={"description": desc},
        )

    agent = _get_agent(req.session_id)

    # Prepend relevant KB cases as context
    cases = search_cases(req.message)
    kb_context = format_cases_for_context(cases)
    message = f"{kb_context}\n{req.message}" if kb_context else req.message

    try:
        reply = agent.chat(message)
        _spawn_extract(list(agent.history), reply)
        return ChatResponse(reply=reply, session_id=req.session_id)
    except ConfirmationRequired as e:
        _pending[req.session_id] = {
            "tool_name":   e.tool_name,
            "tool_input":  e.tool_input,
            "tool_id":     e.tool_id,
            "description": e.description,
            "assistant_msg": e.assistant_msg,
        }
        return ChatResponse(
            reply=f"⚠️ 即将执行危险操作：{e.description}\n\n请确认是否继续？",
            session_id=req.session_id,
            pending_action={"description": e.description},
        )


@app.post("/api/confirm", response_model=ChatResponse)
def confirm(req: ConfirmRequest):
    pending = _pending.pop(req.session_id, None)
    if not pending:
        raise HTTPException(status_code=400, detail="no pending operation")

    if not req.confirmed:
        return ChatResponse(reply="操作已取消。", session_id=req.session_id)

    agent = _get_agent(req.session_id)
    try:
        reply = agent.execute_confirmed(
            pending["tool_name"],
            pending["tool_input"],
            pending["tool_id"],
            pending.get("assistant_msg"),
        )
        _spawn_extract(list(agent.history), reply)
        return ChatResponse(reply=reply, session_id=req.session_id)
    except ConfirmationRequired as e:
        # Rare: another dangerous op follows immediately
        _pending[req.session_id] = {
            "tool_name":   e.tool_name,
            "tool_input":  e.tool_input,
            "tool_id":     e.tool_id,
            "description": e.description,
            "assistant_msg": e.assistant_msg,
        }
        return ChatResponse(
            reply=f"⚠️ 即将执行危险操作：{e.description}\n\n请确认是否继续？",
            session_id=req.session_id,
            pending_action={"description": e.description},
        )


@app.post("/api/reset")
def reset(session_id: str):
    if session_id in _sessions:
        agent = _sessions[session_id]
        _spawn_extract_on_reset(list(agent.history))
        agent.reset()
    _pending.pop(session_id, None)
    return {"ok": True}


@app.get("/api/alerts/stream")
async def alerts_stream():
    """SSE endpoint — pushes inspector alerts to the frontend in real time."""
    if _inspector is None:
        async def disabled():
            yield 'data: {"type":"disabled"}\n\n'
        return StreamingResponse(disabled(), media_type="text/event-stream")

    queue = _inspector.subscribe()

    async def generate():
        try:
            yield 'data: {"type":"connected"}\n\n'
            while True:
                try:
                    alert = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"data: {json.dumps(alert, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"   # keep connection alive
        finally:
            _inspector.unsubscribe(queue)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
