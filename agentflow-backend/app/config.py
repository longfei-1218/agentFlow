"""全局配置：所有环境变量集中在此，代码里不要直接读 os.environ。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_PATH: str = "./data/agentflow.db"

    # LLM（B2 起真正调用；也可通过 /api/settings/llm 在运行时覆盖）
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_DEFAULT_MODEL: str = "gpt-4o-mini"

    # 执行引擎
    MAX_STEPS: int = 8
    RUNNER: str = "demo"  # demo | loop
    DEMO_STEP_DELAY: float = 0.05  # 演示执行器每步延迟（测试里调大以验证取消）

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


settings = Settings()
