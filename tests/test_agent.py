import pytest
from unittest.mock import MagicMock, patch
from k8s.operations import K8sOperations
from agent.confirmation import ConfirmationRequired


def _make_text_block(text="done"):
    block = MagicMock()
    block.type = "text"
    block.text = text
    return block


def _make_tool_use_block(name, input_data, tool_id="tool-1"):
    block = MagicMock()
    block.type = "tool_use"
    block.name = name
    block.input = input_data
    block.id = tool_id
    return block


def _make_response(stop_reason, content):
    resp = MagicMock()
    resp.stop_reason = stop_reason
    resp.content = content
    return resp


@pytest.fixture
def agent(mock_k8s_client):
    with patch("agent.agent.anthropic.Anthropic"):
        from agent.agent import K8sAgent
        a = K8sAgent(K8sOperations(mock_k8s_client))
        a.client = MagicMock()
        return a


class TestK8sAgentChat:
    def test_end_turn_immediately(self, agent):
        agent.client.messages.create.return_value = _make_response(
            "end_turn", [_make_text_block("集群正常")]
        )
        reply = agent.chat("集群状态如何")
        assert reply == "集群正常"
        assert len(agent.history) == 2  # user + assistant

    def test_tool_use_then_end_turn(self, agent, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []

        tool_block = _make_tool_use_block("get_pods", {})
        text_block = _make_text_block("当前没有 Pod 在运行")

        agent.client.messages.create.side_effect = [
            _make_response("tool_use", [tool_block]),
            _make_response("end_turn", [text_block]),
        ]

        reply = agent.chat("列出所有 Pod")
        assert reply == "当前没有 Pod 在运行"
        assert agent.client.messages.create.call_count == 2

    def test_multiple_tool_use_rounds(self, agent, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []
        mock_k8s_client.core.list_namespaced_event.return_value.items = []

        agent.client.messages.create.side_effect = [
            _make_response("tool_use", [_make_tool_use_block("get_pods", {}, "t1")]),
            _make_response("tool_use", [_make_tool_use_block("get_events", {}, "t2")]),
            _make_response("end_turn", [_make_text_block("排查完毕")]),
        ]

        reply = agent.chat("帮我排查问题")
        assert reply == "排查完毕"
        assert agent.client.messages.create.call_count == 3

    def test_dispatch_unknown_tool_returns_error(self, agent):
        result = agent._dispatch_tool("nonexistent_tool", {})
        assert "error" in result

    def test_reset_clears_history(self, agent):
        agent.history = [{"role": "user", "content": "test"}]
        agent.reset()
        assert agent.history == []


class TestK8sAgentConfirmation:
    def test_dangerous_tool_raises_confirmation_required(self, agent):
        tool_block = _make_tool_use_block(
            "scale_deployment",
            {"name": "nginx", "replicas": 0, "namespace": "default"},
            "t-danger",
        )
        agent.client.messages.create.return_value = _make_response("tool_use", [tool_block])

        with pytest.raises(ConfirmationRequired) as exc_info:
            agent.chat("把 nginx 缩为 0")

        cr = exc_info.value
        assert cr.tool_name == "scale_deployment"
        assert cr.tool_id == "t-danger"
        assert "nginx" in cr.description

    def test_dangerous_tool_rolls_back_history(self, agent):
        """assistant(tool_use) must be removed from history before raising."""
        tool_block = _make_tool_use_block(
            "scale_deployment",
            {"name": "nginx", "replicas": 0},
            "t-danger",
        )
        agent.client.messages.create.return_value = _make_response("tool_use", [tool_block])

        with pytest.raises(ConfirmationRequired) as exc_info:
            agent.chat("缩容")

        # history contains only the user message — assistant was rolled back
        assert len(agent.history) == 1
        assert agent.history[0]["role"] == "user"
        assert exc_info.value.assistant_msg is not None

    def test_execute_confirmed_re_appends_assistant_msg(self, agent):
        """execute_confirmed must prepend assistant_msg before tool result."""
        agent.ops.scale_deployment = MagicMock(return_value={"ok": True})
        agent.client.messages.create.return_value = _make_response(
            "end_turn", [_make_text_block("已缩容")]
        )

        fake_assistant_msg = {"role": "assistant", "content": [MagicMock()]}
        reply = agent.execute_confirmed(
            "scale_deployment",
            {"name": "nginx", "replicas": 0, "namespace": "default"},
            "t-danger",
            assistant_msg=fake_assistant_msg,
        )

        assert reply == "已缩容"
        assert agent.history[0] == fake_assistant_msg
        tool_result_msg = agent.history[1]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["tool_use_id"] == "t-danger"

    def test_execute_confirmed_without_assistant_msg(self, agent):
        """execute_confirmed with assistant_msg=None does not crash."""
        agent.ops.scale_deployment = MagicMock(return_value={"ok": True})
        agent.client.messages.create.return_value = _make_response(
            "end_turn", [_make_text_block("完成")]
        )

        reply = agent.execute_confirmed(
            "scale_deployment",
            {"name": "nginx", "replicas": 1, "namespace": "default"},
            "t-x",
            assistant_msg=None,
        )
        assert reply == "完成"


class TestK8sAgentToolDispatch:
    def test_dispatches_to_operations(self, agent, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []
        result = agent._dispatch_tool("get_pods", {"namespace": "kube-system"})
        mock_k8s_client.core.list_namespaced_pod.assert_called_once_with(namespace="kube-system")
        assert isinstance(result, list)

    def test_tool_results_appended_to_history(self, agent, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []
        tool_block = _make_tool_use_block("get_pods", {}, "t1")

        agent.client.messages.create.side_effect = [
            _make_response("tool_use", [tool_block]),
            _make_response("end_turn", [_make_text_block("ok")]),
        ]
        agent.chat("test")

        # history: user, assistant(tool_use), user(tool_result), assistant(end_turn)
        assert len(agent.history) == 4
        tool_result_msg = agent.history[2]
        assert tool_result_msg["role"] == "user"
        assert tool_result_msg["content"][0]["type"] == "tool_result"
        assert tool_result_msg["content"][0]["tool_use_id"] == "t1"
