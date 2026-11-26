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
    MAX_STEPS: int = 8      # 一次运行里允许的 LLM 调用次数上限（防无限自我循环）
    RUNNER: str = "loop"    # loop = 真调模型（llm 节点）；demo = 确定性桩，用于离线回归
    DEMO_STEP_DELAY: float = 0.05  # 节点间停顿（秒），测试里调大以验证取消

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


settings = Settings()
