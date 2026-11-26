"""运行任务注册表：让 cancel / resume / 服务关闭能真正控制后台协程。

P1 的问题：`asyncio.create_task(...)` 的句柄被丢弃，cancel 只改数据库状态，
后台执行器继续发事件、继续写库，最后把状态又改写回 succeeded。
"""
import asyncio
from typing import Coroutine


class RunManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._cancels: dict[str, asyncio.Event] = {}

    def is_active(self, run_id: str) -> bool:
        task = self._tasks.get(run_id)
        return task is not None and not task.done()

    def cancel_token(self, run_id: str) -> asyncio.Event:
        """每个 run 一个协作式取消令牌，执行器在每个可中断点检查它。"""
        token = self._cancels.get(run_id)
        if token is None:
            token = asyncio.Event()
            self._cancels[run_id] = token
        return token

    def request_cancel(self, run_id: str) -> None:
        self.cancel_token(run_id).set()

    def is_cancelled(self, run_id: str) -> bool:
        token = self._cancels.get(run_id)
        return token.is_set() if token else False

    def launch(self, run_id: str, coro: Coroutine) -> asyncio.Task[None]:
        running = self._tasks.get(run_id)
        if running is not None and not running.done():
            raise RuntimeError(f"run {run_id} 已有执行任务在运行")

        task = asyncio.create_task(coro, name=f"run:{run_id}")
        self._tasks[run_id] = task

        def _cleanup(finished: asyncio.Task[None]) -> None:
            # 只清理自己，避免旧任务的回调把新任务的句柄删掉
            if self._tasks.get(run_id) is finished:
                self._tasks.pop(run_id, None)
            self._cancels.pop(run_id, None)

        task.add_done_callback(_cleanup)
        return task

    async def wait(self, run_id: str, timeout: float = 2.0) -> bool:
        """等执行器自行收尾（取消是协作式的，给它一点时间写终态）。"""
        task = self._tasks.get(run_id)
        if task is None:
            return True
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
            return True
        except asyncio.TimeoutError:
            return False

    async def shutdown(self) -> None:
        tasks = [task for task in self._tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()

    @property
    def active_run_ids(self) -> list[str]:
        return [run_id for run_id, task in self._tasks.items() if not task.done()]


run_manager = RunManager()
