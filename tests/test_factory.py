import pytest
from unittest.mock import MagicMock, patch


@pytest.fixture
def ops(mock_k8s_client):
    from k8s.operations import K8sOperations
    return K8sOperations(mock_k8s_client)


def test_factory_returns_anthropic_agent(ops):
    with patch("agent.factory.settings") as mock_settings, \
         patch("agent.agent.anthropic.Anthropic"):
        mock_settings.llm_provider = "anthropic"
        from agent.factory import create_agent
        from agent.agent import K8sAgent
        agent = create_agent(ops)
        assert isinstance(agent, K8sAgent)


def test_factory_returns_deepseek_agent(ops):
    with patch("agent.factory.settings") as mock_settings, \
         patch("agent.deepseek_agent.OpenAI"):
        mock_settings.llm_provider = "deepseek"
        from agent.factory import create_agent
        from agent.deepseek_agent import DeepSeekAgent
        agent = create_agent(ops)
        assert isinstance(agent, DeepSeekAgent)
