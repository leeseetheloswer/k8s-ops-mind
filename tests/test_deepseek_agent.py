import json
import pytest
from unittest.mock import MagicMock, patch
from k8s.operations import K8sOperations
from agent.confirmation import ConfirmationRequired


def _make_tool_call(name, arguments: dict, call_id="call-1"):
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = name
    tc.function.arguments = json.dumps(arguments)
    return tc


def _make_choice(finish_reason, content=None, tool_calls=None):
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = tool_calls
    choice = MagicMock()
    choice.finish_reason = finish_reason
    choice.message = msg
    return choice


def _make_response(choice):
    resp = MagicMock()
    resp.choices = [choice]
    return resp


@pytest.fixture
def agent(mock_k8s_client):
    with patch("agent.deepseek_agent.OpenAI"):
        from agent.deepseek_agent import DeepSeekAgent
        a = DeepSeekAgent(K8sOperations(mock_k8s_client))
        a.client = MagicMock()
        return a


class TestDeepSeekAgentChat:
    def test_end_turn_immediately(self, agent):
        agent.client.chat.completions.create.return_value = _make_response(
            _make_choice("stop", content="一切正常")
        )
        reply = agent.chat("集群状态")
        assert reply == "一切正常"

    def test_tool_call_then_stop(self, agent, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []
        tc = _make_tool_call("get_pods", {})

        agent.client.chat.completions.create.side_effect = [
            _make_response(_make_choice("tool_calls", tool_calls=[tc])),
            _make_response(_make_choice("stop", content="没有 Pod")),
        ]
        reply = agent.chat("列出 Pod")
        assert reply == "没有 Pod"
        assert agent.client.chat.completions.create.call_count == 2

    def test_multiple_tool_rounds(self, agent, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []
        mock_k8s_client.apps.list_namespaced_deployment.return_value.items = []

        agent.client.chat.completions.create.side_effect = [
            _make_response(_make_choice("tool_calls",
                tool_calls=[_make_tool_call("get_pods", {}, "c1")])),
            _make_response(_make_choice("tool_calls",
                tool_calls=[_make_tool_call("get_deployments", {}, "c2")])),
            _make_response(_make_choice("stop", content="排查完毕")),
        ]
        reply = agent.chat("帮我检查")
        assert reply == "排查完毕"
        assert agent.client.chat.completions.create.call_count == 3

    def test_reset_keeps_system_prompt(self, agent):
        agent.history.append({"role": "user", "content": "test"})
        agent.reset()
        assert len(agent.history) == 1
        assert agent.history[0]["role"] == "system"

class TestDeepSeekAgentConfirmation:
    def test_dangerous_tool_raises_confirmation_required(self, agent):
        tc = _make_tool_call(
            "delete_resource",
            {"kind": "Pod", "name": "nginx", "namespace": "default"},
            "c-del",
        )
        agent.client.chat.completions.create.return_value = _make_response(
            _make_choice("tool_calls", tool_calls=[tc])
        )

        with pytest.raises(ConfirmationRequired) as exc_info:
            agent.chat("删除 nginx pod")

        cr = exc_info.value
        assert cr.tool_name == "delete_resource"
        assert cr.tool_id == "c-del"
        assert "nginx" in cr.description

    def test_dangerous_tool_rolls_back_history(self, agent):
        """assistant(tool_calls) must be removed from history before raising."""
        tc = _make_tool_call(
            "delete_resource",
            {"kind": "Pod", "name": "nginx", "namespace": "default"},
            "c-del",
        )
        agent.client.chat.completions.create.return_value = _make_response(
            _make_choice("tool_calls", tool_calls=[tc])
        )
        history_before = len(agent.history)  # system prompt only

        with pytest.raises(ConfirmationRequired) as exc_info:
            agent.chat("删除 nginx")

        # history: system + user — assistant(tool_calls) was rolled back
        assert len(agent.history) == history_before + 1
        assert agent.history[-1]["role"] == "user"
        assert exc_info.value.assistant_msg is not None

    def test_execute_confirmed_re_appends_assistant_msg(self, agent):
        """execute_confirmed must prepend assistant_msg before tool result."""
        agent.ops.delete_resource = MagicMock(return_value={"ok": True})
        agent.client.chat.completions.create.return_value = _make_response(
            _make_choice("stop", content="已删除")
        )

        fake_assistant_msg = MagicMock()
        reply = agent.execute_confirmed(
            "delete_resource",
            {"kind": "Pod", "name": "nginx", "namespace": "default"},
            "c-del",
            assistant_msg=fake_assistant_msg,
        )

        assert reply == "已删除"
        # system, user(chat), assistant_msg, tool_result, assistant(stop)
        assert fake_assistant_msg in agent.history
        tool_msg = agent.history[agent.history.index(fake_assistant_msg) + 1]
        assert tool_msg["role"] == "tool"
        assert tool_msg["tool_call_id"] == "c-del"

    def test_execute_confirmed_without_assistant_msg(self, agent):
        """execute_confirmed with assistant_msg=None does not crash."""
        agent.ops.delete_resource = MagicMock(return_value={"ok": True})
        agent.client.chat.completions.create.return_value = _make_response(
            _make_choice("stop", content="完成")
        )

        reply = agent.execute_confirmed(
            "delete_resource",
            {"kind": "Pod", "name": "nginx", "namespace": "default"},
            "c-x",
            assistant_msg=None,
        )
        assert reply == "完成"


class TestDeepSeekAgentToolResults:
    def test_tool_results_appended_with_role_tool(self, agent, mock_k8s_client):
        mock_k8s_client.core.list_namespaced_pod.return_value.items = []
        tc = _make_tool_call("get_pods", {}, "c1")

        agent.client.chat.completions.create.side_effect = [
            _make_response(_make_choice("tool_calls", tool_calls=[tc])),
            _make_response(_make_choice("stop", content="ok")),
        ]
        agent.chat("test")

        tool_result = agent.history[-2]  # system, user, assistant(tool_calls), tool_result, assistant(stop)
        assert tool_result["role"] == "tool"
        assert tool_result["tool_call_id"] == "c1"
