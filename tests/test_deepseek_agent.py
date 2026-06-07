import json
import pytest
from unittest.mock import MagicMock, patch
from k8s.operations import K8sOperations


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
