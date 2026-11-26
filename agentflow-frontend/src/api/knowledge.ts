/** 知识库 API（R5）：知识库 / 文档 / 检索。 */
import { api } from "./client";

export interface KnowledgeBase {
  id: string;
  name: string;
  collection: string;
  chunkSize: number;
  overlap: number;
  embeddingModel: string;
  docCount: number;
  chunkCount: number;
  createdAt?: string | null;
}

export interface KnowledgeBasePayload {
  name: string;
  chunkSize: number;
  overlap: number;
  embeddingModel?: string;
}

export interface KBDocument {
  id: string;
  kbId: string;
  title: string;
  content: string;
  chunkCount: number;
  createdAt?: string | null;
}

export interface KBHit {
  docId: string;
  title: string;
  seq: number;
  text: string;
  score: number;
}

export interface KBSearchResult {
  kbId: string;
  query: string;
  hits: KBHit[];
  totalChunks: number;
  tookMs: number;
  hint?: string | null;
  extra?: Record<string, unknown>;
}

export const knowledgeApi = {
  list: () => api.get<KnowledgeBase[]>("/knowledge").then((r) => r.data),
  create: (payload: KnowledgeBasePayload) =>
    api.post<KnowledgeBase>("/knowledge", payload).then((r) => r.data),
  update: (id: string, payload: KnowledgeBasePayload) =>
    api.put<KnowledgeBase>(`/knowledge/${id}`, payload).then((r) => r.data),
  remove: (id: string) => api.delete(`/knowledge/${id}`),
  documents: (id: string) =>
    api.get<KBDocument[]>(`/knowledge/${id}/documents`).then((r) => r.data),
  addDocument: (id: string, title: string, content: string) =>
    api
      .post<KBDocument>(`/knowledge/${id}/documents`, { title, content })
      .then((r) => r.data),
  removeDocument: (id: string, docId: string) =>
    api.delete(`/knowledge/${id}/documents/${docId}`),
  search: (id: string, query: string, topK: number, rerank: boolean) =>
    api
      .post<KBSearchResult>(`/knowledge/${id}/search`, { query, topK, rerank })
      .then((r) => r.data),
};
