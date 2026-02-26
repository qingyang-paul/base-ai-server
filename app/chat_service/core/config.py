from pydantic import BaseModel, ConfigDict, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMClientConfig(BaseModel):
    model_config = ConfigDict(extra='ignore')

    limits_max_connections: int = Field(default=100)
    limits_keepalive: int = Field(default=20)
    timeout: float = Field(default=30.0)
    api_key: str = Field(..., description="必须配置 API KEY")
    base_url: str | None = Field(default=None, description="自定义的第三方 API 网关/代理地址")


class Settings(BaseSettings):
    # 自动从环境变量加载，例如 OPENAI__API_KEY=sk-... 就会自动注入
    openai: LLMClientConfig
    gemini: LLMClientConfig
    qwen: LLMClientConfig
    agent_max_loops: int = Field(default=5, description="Maximum iterations for agent loop")

    model_config = SettingsConfigDict(env_nested_delimiter='__', env_file='.env', extra='ignore')


# 实例化全局配置

settings = Settings()

