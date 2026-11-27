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
    # graph = LangGraph（R4 起的默认：条件边 + 有界循环 + checkpointer 中断续跑）
    # loop  = R2 手写 Agent Loop（仅线性拓扑，保留做对照/兜底）
    # demo  = 确定性桩，不联网，用于离线回归
    RUNNER: str = "graph"
    DEMO_STEP_DELAY: float = 0.05  # 节点间停顿（秒），测试里调大以验证取消

    # 本地单用户原型：localhost 与 127.0.0.1 是两个不同 Origin，浏览器不允许混用
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ]
    # 5173 被占用换端口时也不用改配置；只放行本机回环地址
    CORS_ORIGIN_REGEX: str = r"http://(localhost|127\.0\.0\.1)(:\d+)?"


settings = Settings()
