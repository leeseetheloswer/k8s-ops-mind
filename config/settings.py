from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from typing import Optional


class Settings(BaseSettings):
    # Provider selection: "anthropic" | "deepseek"
    llm_provider: str = Field("anthropic", env="LLM_PROVIDER")

    # Anthropic
    anthropic_api_key: Optional[str] = Field(None, env="ANTHROPIC_API_KEY")
    anthropic_model: str = Field("claude-opus-4-8", env="ANTHROPIC_MODEL")

    # DeepSeek (OpenAI-compatible)
    deepseek_api_key: Optional[str] = Field(None, env="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field("https://api.deepseek.com", env="DEEPSEEK_BASE_URL")
    deepseek_model: str = Field("deepseek-chat", env="DEEPSEEK_MODEL")

    # Shared
    agent_max_tokens: int = Field(4096, env="AGENT_MAX_TOKENS")
    kubeconfig: str = Field("~/.kube/config", env="KUBECONFIG")
    k8s_namespace: str = Field("default", env="K8S_NAMESPACE")
    log_level: str = Field("INFO", env="LOG_LEVEL")

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @model_validator(mode="after")
    def check_api_key(self) -> "Settings":
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            raise ValueError("LLM_PROVIDER=anthropic 时必须设置 ANTHROPIC_API_KEY")
        if self.llm_provider == "deepseek" and not self.deepseek_api_key:
            raise ValueError("LLM_PROVIDER=deepseek 时必须设置 DEEPSEEK_API_KEY")
        return self


settings = Settings()
