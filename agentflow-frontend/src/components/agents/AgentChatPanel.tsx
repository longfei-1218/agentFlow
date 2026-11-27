import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fetchEventSource } from "@microsoft/fetch-event-source";
import { ArrowLeft, Bot, MessagesSquare, Plus, Send, Settings2, Trash2 } from "lucide-react";
import { Link } from "react-router-dom";
import { agentsApi } from "@/api/agents";
import { ApiError } from "@/api/client";
import { chatApi, type ChatMessage, type Conversation, type ConversationDetail } from "@/api/chat";
import {
  chatVariable,
  textToVariable,
  variableToText,
  type Agent,
  type AgentVariable,
} from "@/types/agent";

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

interface AgentChatPanelProps {
  agentId: string;
  flowId?: string;
  nodeId?: string;
  /** 工作台内嵌模式：隐藏整页头部和左侧会话栏，使用顶部会话选择器。 */
  embedded?: boolean;
  /** 返回非空字符串时阻止发送；用于“编辑未保存先提示保存”。 */
  beforeSend?: () => string | null;
  sendWarning?: string | null;
  /** 保存 Agent 后递增，让对话面板重新读取变量/提示词配置。 */
  reloadToken?: number;
}

export function AgentChatPanel({
  agentId,
  flowId = "",
  nodeId = "",
  embedded = false,
  beforeSend,
  sendWarning,
  reloadToken = 0,
}: AgentChatPanelProps) {
  const [agent, setAgent] = useState<Agent | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [active, setActive] = useState<ConversationDetail | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState("");
  const [variableText, setVariableText] = useState<Record<string, string>>({});
  const [showVariables, setShowVariables] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [streamRun, setStreamRun] = useState<{ runId: string; conversationId: string } | null>(null);

  const listRef = useRef<HTMLDivElement | null>(null);
  const composingRef = useRef(false);
  const initializingRef = useRef(false);

  const scope = useMemo(
    () => ({ agentId, flowId: flowId || undefined, nodeId: nodeId || undefined }),
    [agentId, flowId, nodeId],
  );

  const scopeInvalid = (!!flowId || !!nodeId) && !(flowId && nodeId);
  const chatVar = chatVariable(agent);
  const extraVariables = useMemo(
    () => agent?.variables.filter((variable) => variable.key !== chatVar?.key && variable.key !== "history") ?? [],
    [agent, chatVar?.key],
  );
  const missingRequired = extraVariables.filter(
    (variable) => variable.required && !(variableText[variable.key] ?? "").trim(),
  );

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
    // StrictMode 会把 effect 跑两遍；不挡住会并发 list(0) + create，凭空多出一条空会话
    if (initializingRef.current) return;
    initializingRef.current = true;
    setLoading(true);
    setError(null);
    if (!agentId) {
      setLoading(false);
      initializingRef.current = false;
      setError("缺少 Agent ID");
      return;
    }
    if (scopeInvalid) {
      setLoading(false);
      initializingRef.current = false;
      setError("flowId 与 nodeId 必须同时提供，或都不提供");
      return;
    }
    try {
      const loaded = await agentsApi.get(agentId);
      setAgent(loaded);
      const initial: Record<string, string> = {};
      loaded.variables.forEach((variable) => {
        initial[variable.key] = variableToText(variable);
      });
      setVariableText(initial);

      let list = await chatApi.list({ agentId, flowId: scope.flowId, nodeId: scope.nodeId });
      if (list.length === 0) {
        const created = await chatApi.create({ agentId, flowId: scope.flowId, nodeId: scope.nodeId }, loaded.name);
        list = [created];
      }
      setConversations(list);
      await loadDetail(list[0].id);
    } catch (err) {
      if (err instanceof ApiError) setError(`${err.message}${err.code ? `（${err.code}）` : ""}`);
      else setError(err instanceof Error ? err.message : "加载会话失败");
    } finally {
      setLoading(false);
      initializingRef.current = false;
    }
  }, [agentId, scope.flowId, scope.nodeId, scopeInvalid, loadDetail]);

  useEffect(() => {
    void initialize();
    return () => setStreamRun(null);
  }, [initialize]);

  // 保存 Agent 后只重载配置，不打断当前对话
  useEffect(() => {
    if (!reloadToken) return;
    let cancelled = false;
    agentsApi.get(agentId)
      .then((loaded) => {
        if (cancelled) return;
        setAgent(loaded);
        setVariableText((prev) => {
          const next = { ...prev };
          loaded.variables.forEach((variable) => {
            if (!(variable.key in next)) next[variable.key] = variableToText(variable);
          });
          return next;
        });
      })
      .catch(() => {
        // 保存后重载失败不打断当前对话，下一次进入会重新读取
      });
    return () => { cancelled = true; };
  }, [agentId, reloadToken]);

  // 订阅当前轮的 run：token 帧就地追加，终态后以服务端会话为准重载
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
        // 重载失败保留已流出的文本，下次发消息再对齐
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

  const buildVariables = (): Record<string, unknown> => {
    const values: Record<string, unknown> = {};
    extraVariables.forEach((variable: AgentVariable) => {
      const text = variableText[variable.key] ?? "";
      if (text.trim() === "") return;
      values[variable.key] = textToVariable(variable.type, text);
    });
    return values;
  };

  const send = async () => {
    const text = input.trim();
    if (!text || !active || sending || missingRequired.length > 0) return;
    const blocked = beforeSend?.();
    if (blocked) {
      setError(blocked);
      return;
    }
    setSending(true);
    setError(null);
    try {
      const turn = await chatApi.sendTurn(active.id, text, buildVariables());
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
      if (err instanceof ApiError) setError(`${err.message}${err.code ? `（${err.code}）` : ""}`);
      else setError(err instanceof Error ? err.message : "发送失败");
    }
  };

  const openConversation = (conversationId: string) => {
    setError(null);
    setStreamRun(null);
    setSending(false);
    void loadDetail(conversationId).catch((err) =>
      setError(err instanceof Error ? err.message : "加载会话失败"),
    );
  };

  const newConversation = async () => {
    if (!agent) return;
    setError(null);
    try {
      const created = await chatApi.create(scope, agent.name);
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
      const list = await chatApi.list(scope);
      if (list.length === 0) {
        const created = await chatApi.create(scope, agent?.name ?? "新对话");
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
    return <div className="h-full flex items-center justify-center text-[13px] text-ink-3">加载 Agent 会话中…</div>;
  }

  if (!agent) {
    return (
      <div className="h-full flex items-center justify-center">
        <div className="card p-6 text-center text-[13px]">
          <div className="text-danger font-semibold">Agent 加载失败</div>
          <div className="text-[12px] text-ink-3 mt-2">{error ?? "Agent 不存在"}</div>
          <Link className="btn inline-flex mt-3" to="/agents">返回 Agent 库</Link>
        </div>
      </div>
    );
  }

  const backTo = flowId ? `/flows/${flowId}` : "/agents";

  return (
    <div className={`h-full flex flex-col ${embedded ? "bg-canvas" : ""}`}>
      {!embedded && (
        <div className="h-[46px] flex-shrink-0 flex items-center gap-3 px-4 bg-white border-b border-line">
          <Link className="btn !py-1" to={backTo}>
            <ArrowLeft size={13} className="inline mr-1 -mt-0.5" />{flowId ? "返回流程" : "Agent 库"}
          </Link>
          <Bot size={16} className="text-primary" />
          <span className="text-[14px] font-semibold truncate">{agent.name}</span>
          <span className={`chip ${flowId ? "!bg-violet-50 !text-violet" : ""}`}>
            {flowId ? `节点作用域 ${nodeId}` : "Agent 直聊"}
          </span>
          <span className="text-[11px] text-ink-3">同一 Agent 在库内 / 不同流程节点各自独立历史</span>
          <Link className="ml-auto text-[12px] text-primary hover:underline" to={`/agents/${agent.id}`}>编辑 Agent</Link>
        </div>
      )}

      {embedded && (
        <div className="h-[40px] flex-shrink-0 flex items-center gap-2 px-3 bg-white border-b border-line">
          <MessagesSquare size={14} className="text-primary shrink-0" />
          <select
            className="field !py-1 !text-[11px] min-w-0 flex-1"
            title={active?.title ?? "会话"}
            value={active?.id ?? ""}
            onChange={(event) => openConversation(event.target.value)}
          >
            {conversations.map((conversation) => (
              <option key={conversation.id} value={conversation.id}>{conversation.title}</option>
            ))}
          </select>
          <button className="text-primary hover:text-primary/80 shrink-0" title="新建对话" onClick={() => void newConversation()}>
            <Plus size={15} />
          </button>
          <button
            className="text-ink-3 hover:text-danger shrink-0 disabled:opacity-40"
            title="删除当前会话"
            disabled={!active}
            onClick={() => { if (active) void removeConversation(active); }}
          >
            <Trash2 size={13} />
          </button>
        </div>
      )}

      {flowId && (
        <div className="px-4 py-1.5 border-b border-violet/20 bg-violet-50 text-[11px] text-violet">
          这里只运行这个 Agent，不执行整条流程。flowId={flowId} · nodeId={nodeId}
        </div>
      )}

      {error && <div className="px-4 py-2 border-b border-danger/20 bg-danger-50 text-[12px] text-danger">{error}</div>}

      {extraVariables.length > 0 && (
        <div className="border-b border-line bg-white">
          <button
            className="w-full flex items-center gap-2 px-4 py-2 text-[12px] text-ink-2 hover:bg-slate-50"
            onClick={() => setShowVariables((value) => !value)}
          >
            <Settings2 size={13} className="text-primary" />
            变量面板（{extraVariables.length} 个，作用于下一轮消息）
            {missingRequired.length > 0 && <span className="text-danger">缺 {missingRequired.map((item) => item.key).join("、")}</span>}
            <span className="ml-auto">{showVariables ? "收起" : "展开"}</span>
          </button>
          {showVariables && (
            <div className="px-4 pb-3 grid grid-cols-[repeat(auto-fill,minmax(160px,1fr))] gap-2">
              {extraVariables.map((variable) => (
                <label key={variable.key} className="block">
                  <span className="flex items-center gap-1 text-[11px] text-ink-2 mb-0.5">
                    <span className="font-mono">{variable.key}</span>
                    {variable.required && <span className="text-danger">*</span>}
                    <span className="ml-auto text-ink-3">{variable.type}</span>
                  </span>
                  {variable.type === "boolean" ? (
                    <select
                      className="field !py-1"
                      value={variableText[variable.key] ?? ""}
                      onChange={(event) => setVariableText((prev) => ({ ...prev, [variable.key]: event.target.value }))}
                    >
                      <option value="">（未填）</option>
                      <option value="true">true</option>
                      <option value="false">false</option>
                    </select>
                  ) : variable.type === "json" ? (
                    <textarea
                      className="field !py-1 font-mono min-h-[52px]"
                      value={variableText[variable.key] ?? ""}
                      placeholder="{}"
                      onChange={(event) => setVariableText((prev) => ({ ...prev, [variable.key]: event.target.value }))}
                    />
                  ) : (
                    <input
                      className="field !py-1"
                      type={variable.type === "number" ? "number" : "text"}
                      value={variableText[variable.key] ?? ""}
                      placeholder={variable.description || (variable.default !== null && variable.default !== undefined ? String(variable.default) : variable.key)}
                      onChange={(event) => setVariableText((prev) => ({ ...prev, [variable.key]: event.target.value }))}
                    />
                  )}
                </label>
              ))}
            </div>
          )}
        </div>
      )}

      <div className="flex-1 min-h-0 flex">
        {!embedded && (
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
                    active?.id === conversation.id ? "border-primary/40 bg-primary-soft" : "border-transparent hover:bg-slate-50"
                  }`}
                  onClick={() => openConversation(conversation.id)}
                >
                  <div className="flex items-center gap-2">
                    <span className="text-[12px] font-medium truncate flex-1">{conversation.title}</span>
                    <button
                      className="text-ink-3 hover:text-danger opacity-0 group-hover:opacity-100"
                      title="删除会话"
                      onClick={(event) => { event.stopPropagation(); void removeConversation(conversation); }}
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
        )}

        <section className="flex-1 min-w-0 flex flex-col bg-canvas">
          <div ref={listRef} className={`flex-1 overflow-y-auto space-y-4 ${embedded ? "px-4 py-4" : "px-6 py-5"}`}>
            {messages.length === 0 && (
              <div className="h-full flex flex-col items-center justify-center text-center">
                <MessagesSquare size={28} className="text-ink-3" />
                <div className="text-[14px] font-semibold mt-2">和「{agent.name}」开始对话</div>
                <div className="text-[12px] text-ink-3 mt-1 max-w-[430px] leading-relaxed">
                  每发一句话都会创建一次 Agent run。
                  {chatVar
                    ? `消息会填进 Agent 的 ${chatVar.key} 变量；`
                    : "该 Agent 没有声明变量，消息会追加到提示词模板末尾；"}
                  {agent.variables.some((variable) => variable.key === "history") && " 历史会自动注入 history。"}
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
                      {message.runId && <Link className="hover:text-primary" to={`/runs/${message.runId}`}>回放</Link>}
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
            {sendWarning && (
              <div className="mb-2 rounded-sm border border-warn/30 bg-warn-50 px-2.5 py-1.5 text-[11px] text-warn">
                {sendWarning}
              </div>
            )}
            <div className="flex items-end gap-2">
              <textarea
                className="field min-h-[46px] max-h-[140px] resize-y"
                rows={2}
                value={input}
                disabled={sending}
                placeholder={sending ? "上一轮还在运行…" : "输入消息，Enter 发送 / Shift+Enter 换行"}
                onChange={(event) => setInput(event.target.value)}
                onCompositionStart={() => { composingRef.current = true; }}
                onCompositionEnd={() => { composingRef.current = false; }}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey && !composingRef.current) {
                    event.preventDefault();
                    void send();
                  }
                }}
              />
              <button className="btn-primary !py-2" disabled={sending || !input.trim() || missingRequired.length > 0} onClick={() => void send()}>
                <Send size={14} className="inline mr-1 -mt-0.5" />发送
              </button>
            </div>
            <div className="text-[10px] text-ink-3 mt-1.5">
              {missingRequired.length > 0
                ? `必填变量未填：${missingRequired.map((item) => item.key).join("、")}`
                : "对话历史取最近 6 轮 / 3000 字（硬截断）；每轮都会创建 targetType=agent 的 run。"}
            </div>
          </div>
        </section>
      </div>
    </div>
  );
}
