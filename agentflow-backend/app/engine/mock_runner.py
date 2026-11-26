"""兼容旧引用：演示执行器已迁移到 app/engine/demo_runner.py。

保留该模块名是为了不破坏历史文档/前端示例里的 import 路径；
新代码请直接引用 app.engine.demo_runner。
"""
from app.engine.demo_runner import run_demo_flow as run_mock_flow  # noqa: F401
