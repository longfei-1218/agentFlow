/** 对话模式 API（R5.1）：会话 CRUD + 发一轮消息（内部创建一次普通 run）。 */
import { api } from "./client";

export type ChatRole = "user" | "assistant";

export interface Conversation {
  id: string;
  flowId: string;
  title: string;
  createdAt: string;
  updatedAt: string;
}

export interface ChatMessage {
  id: string;
  role: ChatRole;
  content: string;
  turnId: string;
  runId?: string | null;
  status?: string | null;
  error?: string | null;
  tokens: number;
  cost: number;
}

export interface ConversationDetail extends Conversation {
  messages: ChatMessage[];
}

export interface ChatTurnResult {
  conversationId: string;
  turnId: string;
  runId: string;
  status: string;
}

export const chatApi = {
  list: (flowId?: string) =>
    api
      .get<Conversation[]>("/chat/conversations", { params: flowId ? { flow_id: flowId } : undefined })
      .then((r) => r.data),
  create: (flowId: string, title = "") =>
    api.post<Conversation>("/chat/conversations", { flowId, title }).then((r) => r.data),
  get: (id: string) => api.get<ConversationDetail>(`/chat/conversations/${id}`).then((r) => r.data),
  remove: (id: string) => api.delete(`/chat/conversations/${id}`),
  sendTurn: (id: string, content: string) =>
    api
      .post<ChatTurnResult>(`/chat/conversations/${id}/turns`, { content })
      .then((r) => r.data),
};
