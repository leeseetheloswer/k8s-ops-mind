"""
FastAPI backend — wraps K8sAgent and exposes a REST API for the React frontend.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from config.settings import settings
from k8s.client import K8sClient
from k8s.operations import K8sOperations
from agent.factory import create_agent

app = FastAPI(title="K8s Ops Agent API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# session_id -> agent instance
_sessions: dict = {}


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


# ------------------------------------------------------------------ #
# Routes
# ------------------------------------------------------------------ #

@app.get("/api/health")
def health():
    return {"status": "ok", "provider": settings.llm_provider}


@app.post("/api/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    agent = _get_agent(req.session_id)
    reply = agent.chat(req.message)
    return ChatResponse(reply=reply, session_id=req.session_id)


@app.post("/api/reset")
def reset(session_id: str):
    if session_id in _sessions:
        _sessions[session_id].reset()
    return {"ok": True}
