import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient


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
        # 清空 sessions 避免跨测试污染
        import server
        server._sessions.clear()
        yield TestClient(app)


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
