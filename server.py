"""
FastAPI backend — wraps K8sAgent and exposes a REST API for the React frontend.
"""
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any

from config.settings import settings
from k8s.client import K8sClient
from k8s.operations import K8sOperations
from agent.factory import create_agent
from agent.confirmation import ConfirmationRequired

app = FastAPI(title="K8s Ops Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_sessions: dict = {}
_pending: dict = {}   # session_id → {tool_name, tool_input, tool_id, description}


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
            reply=f"⚠️ 有待确认的危险操作，请先处理后再发送新消息。",
            session_id=req.session_id,
            pending_action={"description": desc},
        )
    agent = _get_agent(req.session_id)
    try:
        reply = agent.chat(req.message)
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
        _sessions[session_id].reset()
    _pending.pop(session_id, None)
    return {"ok": True}
