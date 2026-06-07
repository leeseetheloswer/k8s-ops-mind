from k8s.operations import K8sOperations
from config.settings import settings


def create_agent(ops: K8sOperations):
    """Return the appropriate agent based on LLM_PROVIDER."""
    if settings.llm_provider == "deepseek":
        from agent.deepseek_agent import DeepSeekAgent
        return DeepSeekAgent(ops)

    from agent.agent import K8sAgent
    return K8sAgent(ops)
