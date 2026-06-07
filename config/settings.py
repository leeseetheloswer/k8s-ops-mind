from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from typing import Optional


class Settings(BaseSettings):
    # Provider selection: "anthropic" | "deepseek"
    llm_provider: str = "anthropic"

    # Anthropic
    anthropic_api_key: Optional[str] = None
    anthropic_model: str = "claude-opus-4-8"

    # DeepSeek (OpenAI-compatible)
    deepseek_api_key: Optional[str] = None
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"

    # Shared
    agent_max_tokens: int = 4096
    kubeconfig: str = "~/.kube/config"
    k8s_namespace: str = "default"
    log_level: str = "INFO"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def check_api_key(self) -> "Settings":
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic 时必须设置 ANTHROPIC_API_KEY")
        if self.llm_provider == "deepseek" and not self.deepseek_api_key:
            raise ValueError("LLM_PROVIDER=deepseek 时必须设置 DEEPSEEK_API_KEY")
        return self


settings = Settings()
