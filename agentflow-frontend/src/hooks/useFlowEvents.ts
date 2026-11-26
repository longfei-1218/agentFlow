import { useEffect } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { useFlowStore } from "@/store/flowStore";
import { useRunStore } from "@/store/runStore";
import type { RunEvent } from "@/types/run";

const TERMINAL_EVENTS = new Set(["run_completed", "run_failed"]);

/** 订阅运行事件流：按 seq 去重，断线自动重连并带 Last-Event-ID 续推。 */
export function useFlowEvents(runId: string | null): void {
  const appendEvent = useRunStore((s) => s.appendEvent);

  useEffect(() => {
    if (!runId) return;
    const controller = new AbortController();

    fetchEventSource(`/api/runs/${runId}/events`, {
      method: "GET",
      headers: { "Last-Event-ID": String(useRunStore.getState().lastSeq) },
      signal: controller.signal,
      openWhenHidden: true,
      async onopen(response) {
        if (!response.ok) throw new Error(`SSE 连接失败: ${response.status}`);
      },
      async onmessage(message) {
        if (!message.data) return;
        let event: RunEvent;
        try {
          event = JSON.parse(message.data) as RunEvent;
        } catch {
          return;
        }
        if (event.seq <= useRunStore.getState().lastSeq) return;

        appendEvent(event);

        const setRuntime = useFlowStore.getState().setRuntime;
        if (event.type === "node_started" && event.nodeId) setRuntime(event.nodeId, "running");
        if (event.type === "node_completed" && event.nodeId) setRuntime(event.nodeId, "done");
        if (event.type === "human_required" && event.nodeId) setRuntime(event.nodeId, "running");
        if (event.type === "run_failed" && event.nodeId) setRuntime(event.nodeId, "error");

        // 终态后主动断开：历史回放页不必再挂一个连接等服务端超时
        if (TERMINAL_EVENTS.has(event.type)) controller.abort();
      },
      onerror(error) {
        throw error; // 交给 fetch-event-source 的指数退避重连
      },
    }).catch(() => {
      // abort 触发的取消是预期行为，静默处理，避免控制台报未捕获异常
    });

    return () => controller.abort();
  }, [runId, appendEvent]);
}
