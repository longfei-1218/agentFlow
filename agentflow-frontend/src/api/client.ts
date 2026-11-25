import axios from "axios";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
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
    );
  },
);
