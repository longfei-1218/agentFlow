import axios from "axios";

export interface ApiIssue {
  nodeId?: string | null;
  field?: string | null;
  message: string;
}

/** 后端统一错误体：{ code, message, detail }，detail 里可能带逐条校验问题。 */
export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public detail: ApiIssue[] = [],
    /** 原始 detail：Agent 校验返回的是 {valid,errors,warnings} 对象，不是 issue 数组 */
    public rawDetail: unknown = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

function normalizeIssues(detail: unknown): ApiIssue[] {
  if (!Array.isArray(detail)) return [];
  return detail.map((item) => {
    if (typeof item === "string") return { message: item };
    const record = item as Record<string, unknown>;
    return {
      nodeId: (record.nodeId as string) ?? null,
      field: (record.field as string) ?? null,
      message: String(record.message ?? record.msg ?? "校验失败"),
    };
  });
}

export const api = axios.create({
  baseURL: "/api",
  timeout: 15000,
  headers: { "Content-Type": "application/json" },
});

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const data = error.response?.data;
    throw new ApiError(
      error.response?.status ?? 0,
      data?.code ?? "NETWORK_ERROR",
      data?.message ?? error.message ?? "请求失败",
      normalizeIssues(data?.detail),
      data?.detail,
    );
  },
);
