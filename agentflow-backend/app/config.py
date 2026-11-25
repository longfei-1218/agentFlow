"""全局配置：所有环境变量集中在此，代码里不要直接读 os.environ。"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    DATABASE_PATH: str = "./data/agentflow.db"
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str = ""
    LLM_DEFAULT_MODEL: str = "gpt-4o-mini"
    MAX_STEPS: int = 8
    CORS_ORIGINS: list[str] = ["http://localhost:5173"]


settings = Settings()
