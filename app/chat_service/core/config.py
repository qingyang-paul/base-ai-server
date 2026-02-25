from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMClientConfig(BaseModel):
    limits_max_connections: int = Field(default=100)
    limits_keepalive: int = Field(default=20)
    timeout: float = Field(default=30.0)
    api_key: str = Field(..., description="必须配置 API KEY")
    base_url: str | None = Field(default=None, description="自定义的第三方 API 网关/代理地址")

    # Default Generation Params
    model: str = Field(..., description="必须选择模型")
    temperature: float = Field(default=1.0)
    max_tokens: int = Field(default=8192)
    
    # Provider Specific Defaults (Optional)
    frequency_penalty: float = Field(default=0.0) # OpenAI
    top_k: int = Field(default=40)                # Gemini
    max_output_tokens: int = Field(default=8192)  # Gemini


class Settings(BaseSettings):
    # 自动从环境变量加载，例如 OPENAI__API_KEY=sk-... 就会自动注入
    openai: LLMClientConfig
    gemini: LLMClientConfig
    qwen: LLMClientConfig
    agent_max_loops: int = Field(default=5, description="Maximum iterations for agent loop")

    model_config = SettingsConfigDict(env_nested_delimiter='__', env_file='.env', extra='ignore')


# 实例化全局配置

settings = Settings()

