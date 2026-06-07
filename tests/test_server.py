import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient
from agent.confirmation import ConfirmationRequired


@pytest.fixture
def client():
    with patch("k8s.client.K8sClient.connect", return_value=True), \
         patch("agent.agent.anthropic.Anthropic"), \
         patch("agent.factory.settings") as ms:
        ms.llm_provider = "anthropic"
        ms.anthropic_api_key = "sk-test"
        ms.anthropic_model = "claude-opus-4-8"
        ms.deepseek_api_key = "sk-test"
        ms.kubeconfig = "~/.kube/config"
        ms.k8s_namespace = "default"
        ms.agent_max_tokens = 4096

        from server import app
        import server
        server._sessions.clear()
        server._pending.clear()
        yield TestClient(app)
        server._pending.clear()


class TestHealthEndpoint:
    def test_returns_ok(self, client):
        with patch("server.settings") as ms:
            ms.llm_provider = "anthropic"
            resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestChatEndpoint:
    def test_returns_reply(self, client):
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "当前没有 Pod"

        with patch("server._get_agent", return_value=mock_agent):
            resp = client.post("/api/chat", json={
                "message": "列出所有 Pod",
                "session_id": "test-session-1",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["reply"] == "当前没有 Pod"
        assert data["session_id"] == "test-session-1"

    def test_passes_message_to_agent(self, client):
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "ok"

        with patch("server._get_agent", return_value=mock_agent):
            client.post("/api/chat", json={
                "message": "查看节点状态",
                "session_id": "test-session-2",
            })

        mock_agent.chat.assert_called_once_with("查看节点状态")

    def test_returns_pending_action_on_dangerous_tool(self, client):
        """When agent raises ConfirmationRequired, response includes pending_action."""
        import server
        server._pending.clear()

        mock_agent = MagicMock()
        mock_agent.chat.side_effect = ConfirmationRequired(
            "scale_deployment",
            {"name": "nginx", "replicas": 0, "namespace": "default"},
            "tool-1",
            "将 Deployment nginx 副本数调整为 0（namespace: default）",
            assistant_msg={"role": "assistant", "content": []},
        )

        with patch("server._get_agent", return_value=mock_agent):
            resp = client.post("/api/chat", json={
                "message": "缩容 nginx 到 0",
                "session_id": "sess-danger",
            })

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_action"] is not None
        assert "nginx" in data["pending_action"]["description"]
        assert "sess-danger" in server._pending

    def test_chat_blocked_when_pending_exists(self, client):
        """New messages are blocked while a confirmation is pending."""
        import server
        server._pending["sess-blocked"] = {
            "tool_name": "delete_resource",
            "tool_input": {},
            "tool_id": "t1",
            "description": "删除 Pod nginx",
            "assistant_msg": None,
        }

        resp = client.post("/api/chat", json={
            "message": "另一条消息",
            "session_id": "sess-blocked",
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["pending_action"] is not None
        assert data["pending_action"]["description"] == "删除 Pod nginx"

    def test_no_pending_action_on_normal_reply(self, client):
        mock_agent = MagicMock()
        mock_agent.chat.return_value = "正常回复"

        with patch("server._get_agent", return_value=mock_agent):
            resp = client.post("/api/chat", json={
                "message": "查询 Pod",
                "session_id": "sess-normal",
            })

        data = resp.json()
        assert data["pending_action"] is None


class TestConfirmEndpoint:
    def test_confirm_executes_operation(self, client):
        """confirmed=True calls execute_confirmed with stored args and assistant_msg."""
        import server
        fake_msg = {"role": "assistant", "content": []}
        server._pending["sess-confirm"] = {
            "tool_name": "scale_deployment",
            "tool_input": {"name": "nginx", "replicas": 3, "namespace": "default"},
            "tool_id": "t-conf",
            "description": "扩容",
            "assistant_msg": fake_msg,
        }

        mock_agent = MagicMock()
        mock_agent.execute_confirmed.return_value = "扩容完成"

        with patch("server._get_agent", return_value=mock_agent):
            resp = client.post("/api/confirm", json={
                "session_id": "sess-confirm",
                "confirmed": True,
            })

        assert resp.status_code == 200
        assert resp.json()["reply"] == "扩容完成"
        mock_agent.execute_confirmed.assert_called_once_with(
            "scale_deployment",
            {"name": "nginx", "replicas": 3, "namespace": "default"},
            "t-conf",
            fake_msg,
        )
        assert "sess-confirm" not in server._pending

    def test_confirm_cancel_returns_message(self, client):
        """confirmed=False returns cancel message and clears pending."""
        import server
        server._pending["sess-cancel"] = {
            "tool_name": "delete_resource",
            "tool_input": {},
            "tool_id": "t-can",
            "description": "删除",
            "assistant_msg": None,
        }

        resp = client.post("/api/confirm", json={
            "session_id": "sess-cancel",
            "confirmed": False,
        })

        assert resp.status_code == 200
        assert "取消" in resp.json()["reply"]
        assert "sess-cancel" not in server._pending

    def test_confirm_no_pending_returns_400(self, client):
        """No pending operation → 400 error."""
        import server
        server._pending.pop("sess-none", None)

        resp = client.post("/api/confirm", json={
            "session_id": "sess-none",
            "confirmed": True,
        })

        assert resp.status_code == 400

    def test_confirm_pending_cleared_after_execute(self, client):
        """Pending entry is removed after successful execution."""
        import server
        server._pending["sess-clear"] = {
            "tool_name": "scale_deployment",
            "tool_input": {"name": "nginx", "replicas": 1, "namespace": "default"},
            "tool_id": "t-clr",
            "description": "扩容",
            "assistant_msg": None,
        }

        mock_agent = MagicMock()
        mock_agent.execute_confirmed.return_value = "完成"

        with patch("server._get_agent", return_value=mock_agent):
            client.post("/api/confirm", json={
                "session_id": "sess-clear",
                "confirmed": True,
            })

        assert "sess-clear" not in server._pending


class TestResetEndpoint:
    def test_reset_existing_session(self, client):
        mock_agent = MagicMock()
        import server
        server._sessions["sess-reset"] = mock_agent

        resp = client.post("/api/reset", params={"session_id": "sess-reset"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        mock_agent.reset.assert_called_once()

    def test_reset_nonexistent_session_is_noop(self, client):
        resp = client.post("/api/reset", params={"session_id": "nonexistent"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_reset_clears_pending(self, client):
        """Reset must also clear any pending confirmation for that session."""
        import server
        server._pending["sess-rp"] = {"description": "test"}
        server._sessions["sess-rp"] = MagicMock()

        client.post("/api/reset", params={"session_id": "sess-rp"})

        assert "sess-rp" not in server._pending
