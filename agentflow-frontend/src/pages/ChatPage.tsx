import { useCallback, useEffect, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { ArrowLeft, MessagesSquare, Plus, Send, Trash2 } from "lucide-react";
import { Link, useParams } from "react-router-dom";
import { chatApi, type ChatMessage, type Conversation, type ConversationDetail } from "@/api/chat";
import { flowsApi } from "@/api/flows";
import type { Flow } from "@/types/flow";
import { ApiError } from "@/api/client";

const STATUS_LABEL: Record<string, string> = {
  pending: "排队中",
  running: "生成中",
  waiting_human: "等待审批",
  succeeded: "完成",
  failed: "失败",
  cancelled: "已取消",
};

const ACTIVE_STATUSES = new Set(["pending", "running"]);

function lastPendingAssistant(messages: ChatMessage[]): ChatMessage | undefined {
  return [...messages]
    .reverse()
    .find(
      (message) =>
        message.role === "assistant" &&
        !!message.runId &&
        ACTIVE_STATUSES.has(message.status ?? ""),
    );
}

export function ChatPage() {
  // 路由是 /flows/:id/chat，参数名是 id；这里必须解构 id，否则 flowId 恒为空，
  // 列表会退化成“全部会话”，看起来就是所有流程共享同一份历史
  const { id: flowId = "" } = useParams<{ id: string }>();
  const [flow, setFlow] = useState<Flow | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<ConversationDetail | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [streamRun, setStreamRun] = useState<{ runId: string; conversationId: string } | null>(null);

  const listRef = useRef<HTMLDivElement | null>(null);
  const composingRef = useRef(false);

  const loadDetail = useCallback(
    async (conversationId: string, subscribePending = true) => {
      const detail = await chatApi.get(conversationId);
      setActive(detail);
      setMessages(detail.messages);
      if (subscribePending) {
        const pending = lastPendingAssistant(detail.messages);
        if (pending?.runId) {
          setStreamRun({ runId: pending.runId, conversationId: detail.id });
          setSending(true);
        }
      }
      return detail;
    },
    [],
  );

  const initialize = useCallback(async () => {
    setLoading(true);
    setError(null);
    if (!flowId) {
      setLoading(false);
      setError("缺少流程 ID，无法打开对话");
      return;
    }
    try {
      const loadedFlow = await flowsApi.get(flowId);
      setFlow(loadedFlow);
      let list = await chatApi.list(flowId);
      if (list.length === 0) {
        const created = await chatApi.create(flowId, loadedFlow.name);
        list = [created];
      }
      setConversations(list);
      await loadDetail(list[0].id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "加载会话失败");
    } finally {
      setLoading(false);
    }
  }, [flowId, loadDetail]);

  useEffect(() => {
    void initialize();
    return () => {
      setStreamRun(null);
    };
  }, [initialize]);

  // 订阅当前轮的 run：token 帧就地追加到该 assistant 气泡，终态后以服务端会话为准重载
  useEffect(() => {
    if (!streamRun) return;
    const controller = new AbortController();
    let lastSeq = 0;
    let finished = false;
    let disposed = false;

    const finish = async (conversationId: string) => {
      if (finished) return;
      finished = true;
      controller.abort();
      setSending(false);
      setStreamRun(null);
      try {
        const detail = await chatApi.get(conversationId);
        setActive(detail);
        setMessages(detail.messages);
        setConversations((prev) =>
          prev.map((item) =>
            item.id === detail.id ? { ...item, title: detail.title, updatedAt: detail.updatedAt } : item,
          ),
        );
      } catch {
        // 重载失败就保留已经流出来的文本，下一次发消息会再对齐
      }
    };

    fetchEventSource(`/api/runs/${streamRun.runId}/events`, {
      method: "GET",
      headers: { "Last-Event-ID": "0" },
      signal: controller.signal,
      openWhenHidden: true,
      async onopen(response) {
        if (!response.ok) throw new Error(`SSE 连接失败: ${response.status}`);
      },
      async onmessage(message) {
        if (!message.data) return;
        let event: { seq: number; type: string; payload?: Record<string, unknown> };
        try {
          event = JSON.parse(message.data);
        } catch {
          return;
        }
        if (event.seq <= lastSeq) return;
        lastSeq = event.seq;
        if (event.type === "token") {
          const text = String(event.payload?.text ?? "");
          if (!text) return;
          setMessages((prev) =>
            prev.map((item) =>
              item.role === "assistant" && item.runId === streamRun.runId
                ? { ...item, content: item.content + text, status: "running" }
                : item,
            ),
          );
        }
        if (event.type === "run_completed" || event.type === "run_failed") {
          void finish(streamRun.conversationId);
        }
      },
      onerror(err) {
        throw err;
      },
    }).catch(() => {
      // abort 是预期行为；非预期断流要让输入框恢复可用，别把 sending 永久卡住
      if (!finished && !disposed) {
        setSending(false);
        setStreamRun(null);
        setError("SSE 连接中断，点左侧会话可重新加载当前状态");
      }
    });

    return () => {
      disposed = true;
      controller.abort();
    };
  }, [streamRun]);

  useEffect(() => {
    const node = listRef.current;
    if (node) node.scrollTop = node.scrollHeight;
  }, [messages, streamRun]);

  const send = async () => {
    const text = input.trim();
    if (!text || !active || sending) return;
    setSending(true);
    setError(null);
    try {
      const turn = await chatApi.sendTurn(active.id, text);
      setInput("");
      const detail = await chatApi.get(active.id);
      setActive(detail);
      setMessages(detail.messages);
      setConversations((prev) =>
        prev.map((item) =>
          item.id === detail.id ? { ...item, title: detail.title, updatedAt: detail.updatedAt } : item,
        ),
      );
      const assistant = lastPendingAssistant(detail.messages);
      if (assistant?.runId === turn.runId) {
        setStreamRun({ runId: turn.runId, conversationId: active.id });
      } else {
        setSending(false);
      }
    } catch (err) {
      setSending(false);
      if (err instanceof ApiError) {
        setError(`${err.message}${err.code ? `（${err.code}）` : ""}`);
      } else {
        setError(err instanceof Error ? err.message : "发送失败");
      }
    }
  };

  const newConversation = async () => {
    if (!flow) return;
    setError(null);
    try {
      const created = await chatApi.create(flow.id, flow.name);
      setConversations((prev) => [created, ...prev]);
      await loadDetail(created.id, false);
      setStreamRun(null);
      setSending(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "新建会话失败");
    }
  };

  const removeConversation = async (conversation: Conversation) => {
    if (!window.confirm(`删除会话「${conversation.title}」？聊天记录会一起删掉。`)) return;
    try {
      await chatApi.remove(conversation.id);
      const list = await chatApi.list(flowId);
      if (list.length === 0) {
        const created = await chatApi.create(flowId, flow?.name ?? "新对话");
        setConversations([created]);
        await loadDetail(created.id, false);
      } else {
        setConversations(list);
        if (active?.id === conversation.id) await loadDetail(list[0].id);
      }
      setStreamRun(null);
      setSending(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除会话失败");
    }
  };

  if (loading) {
    return <div className="h-full flex items-center justify-center text-[13px] text-ink-3">加载对话中…</div>;
  }

  if (!flow) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="card p-6 text-center text-[13px]">
          <div className="text-danger font-semibold">流程加载失败</div>
          <div className="text-ink-3 mt-2">{error ?? "流程不存在"}</div>
          <Link className="btn inline-flex mt-3" to="/flows">
            返回流程列表
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="h-full flex flex-col">
      <div className="h-[46px] flex-shrink-0 flex items-center gap-3 px-4 bg-white border-b border-line">
        <Link className="btn !py-1" to={`/flows/${flow.id}`}>
          <ArrowLeft size={13} className="inline mr-1 -mt-0.5" />流程
        </Link>
        <MessagesSquare size={16} className="text-primary" />
        <span className="text-[14px] font-semibold truncate">{flow.name}</span>
        <span className="chip">v{flow.version}</span>
        <span className="text-[11px] text-ink-3">每轮消息都会执行整条流程，历史自动拼进 {"{{history}}"}</span>
        <Link className="ml-auto text-[12px] text-primary hover:underline" to={`/flows/${flow.id}`}>
          编辑流程
        </Link>
      </div>

      {error && (
        <div className="px-4 py-2 border-b border-danger/20 bg-danger-50 text-[12px] text-danger">{error}</div>
      )}

      <div className="flex-1 min-h-0 flex">
        <aside className="w-[230px] flex-shrink-0 border-r border-line bg-white flex flex-col">
          <div className="flex items-center gap-2 px-3 py-2.5 border-b border-line">
            <span className="text-[12px] font-semibold">会话</span>
            <span className="badge badge-gray">{conversations.length}</span>
            <button className="ml-auto text-primary hover:text-primary/80" title="新建对话" onClick={() => void newConversation()}>
              <Plus size={15} />
            </button>
          </div>
          <div className="flex-1 overflow-y-auto p-2 space-y-1">
            {conversations.map((conversation) => (
              <div
                key={conversation.id}
                className={`group rounded-sm px-2.5 py-2 cursor-pointer border ${
                  active?.id === conversation.id
                    ? "border-primary/40 bg-primary-soft"
                    : "border-transparent hover:bg-slate-50"
                }`}
                onClick={() => {
                  setError(null);
                  setStreamRun(null);
                  setSending(false);
                  void loadDetail(conversation.id).catch((err) =>
                    setError(err instanceof Error ? err.message : "加载会话失败"),
                  );
                }}
              >
                <div className="flex items-center gap-2">
                  <span className="text-[12px] font-medium truncate flex-1">{conversation.title}</span>
                  <button
                    className="text-ink-3 hover:text-danger opacity-0 group-hover:opacity-100"
                    title="删除会话"
                    onClick={(event) => {
                      event.stopPropagation();
                      void removeConversation(conversation);
                    }}
                  >
                    <Trash2 size={12} />
                  </button>
                </div>
                <div className="text-[10px] text-ink-3 mt-0.5">
                  {new Date(conversation.updatedAt).toLocaleString("zh-CN", { hour12: false })}
                </div>
              </div>
            ))}
          </div>
        </aside>

        <section className="flex-1 min-w-0 flex flex-col bg-canvas">
          <div ref={listRef} className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
            {messages.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-center">
                <MessagesSquare size={28} className="text-ink-3" />
                <div className="text-[14px] font-semibold mt-2">和「{flow.name}」开始对话</div>
                <div className="text-[12px] text-ink-3 mt-1 max-w-[420px] leading-relaxed">
                  每发一句话都会创建一次真实 run：入口是 query，上一轮问答会作为 history 注入。
                  运行记录仍可在「运行历史」里逐条回放。
                </div>
              </div>
            )}

            {messages.map((message) =>
              message.role === "user" ? (
                <div key={message.id} className="flex justify-end">
                  <div className="max-w-[72%] rounded-lg bg-primary text-white px-3.5 py-2 text-[13px] leading-relaxed whitespace-pre-wrap">
                    {message.content}
                  </div>
                </div>
              ) : (
                <div key={message.id} className="flex justify-start">
                  <div className="max-w-[76%] min-w-[120px]">
                    <div className="rounded-lg border border-line bg-white px-3.5 py-2 text-[13px] leading-relaxed whitespace-pre-wrap">
                      {message.content || (
                        <span className="text-ink-3">
                          {ACTIVE_STATUSES.has(message.status ?? "") ? "正在生成…" : "（本轮没有文本输出）"}
                        </span>
                      )}
                      {ACTIVE_STATUSES.has(message.status ?? "") && (
                        <span className="inline-block w-[2px] h-[13px] bg-primary ml-0.5 align-middle animate-pulse" />
                      )}
                    </div>
                    <div className="flex items-center gap-2 mt-1 px-1 text-[10px] text-ink-3">
                      <span>{STATUS_LABEL[message.status ?? ""] ?? message.status}</span>
                      {message.tokens > 0 && <span>{message.tokens} tokens</span>}
                      {message.cost > 0 && <span>¥{message.cost.toFixed(6)}</span>}
                      {message.runId && (
                        <Link className="hover:text-primary" to={`/runs/${message.runId}`}>
                          回放
                        </Link>
                      )}
                    </div>
                    {message.status === "failed" && message.error && (
                      <div className="text-[11px] text-danger mt-0.5 px-1">{message.error}</div>
                    )}
                  </div>
                </div>
              ),
            )}
          </div>

          <div className="flex-shrink-0 border-t border-line bg-white px-4 py-3">
            <div className="flex items-end gap-2">
              <textarea
                className="field min-h-[46px] max-h-[140px] resize-y"
                rows={2}
                value={input}
                disabled={sending}
                placeholder={sending ? "上一轮还在运行…" : "输入消息，Enter 发送 / Shift+Enter 换行"}
                onChange={(event) => setInput(event.target.value)}
                onCompositionStart={() => {
                  composingRef.current = true;
                }}
                onCompositionEnd={() => {
                  composingRef.current = false;
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !composingRef.current) {
                    event.preventDefault();
                    void send();
                  }
                }}
              />
              <button className="btn-primary !py-2" disabled={sending || !input.trim()} onClick={() => void send()}>
                <Send size={14} className="inline mr-1 -mt-0.5" />
                发送
              </button>
            </div>
            <div className="text-[10px] text-ink-3 mt-1.5">
              对话历史取最近 6 轮 / 3000 字（硬截断）；长短期记忆（摘要 + 向量召回）后续接入。
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
