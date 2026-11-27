/** Agent 对话 API：作用域 agentId + flowId? + nodeId?，每轮一次 Agent Run。 */
import { api } from "./client";

export type ChatRole = "user" | "assistant";

export interface ConversationScope {
  agentId: string;
  flowId?: string;
  nodeId?: string;
}

export interface Conversation {
  id: string;
  agentId: string;
  flowId?: string | null;
  nodeId?: string | null;
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
  list: (scope: ConversationScope) =>
    api
      .get<Conversation[]>("/chat/conversations", {
        params: {
          agent_id: scope.agentId,
          flow_id: scope.flowId || undefined,
          node_id: scope.nodeId || undefined,
        },
      })
      .then((r) => r.data),
  create: (scope: ConversationScope, title = "") =>
    api
      .post<Conversation>("/chat/conversations", {
        agentId: scope.agentId,
        flowId: scope.flowId || undefined,
        nodeId: scope.nodeId || undefined,
        title,
      })
      .then((r) => r.data),
  get: (id: string) => api.get<ConversationDetail>(`/chat/conversations/${id}`).then((r) => r.data),
  remove: (id: string) => api.delete(`/chat/conversations/${id}`),
  sendTurn: (id: string, content: string, variables: Record<string, unknown> = {}) =>
    api
      .post<ChatTurnResult>(`/chat/conversations/${id}/turns`, { content, variables })
      .then((r) => r.data),
};
