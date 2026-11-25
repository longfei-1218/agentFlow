/** 设计 token 严格对齐 agentflow-studio-ui.html 的 :root 变量 */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        bg: "#f6f7f9",
        panel: "#ffffff",
        line: "#e5e7eb",
        "line-strong": "#d1d5db",
        ink: { DEFAULT: "#111827", 2: "#4b5563", 3: "#9ca3af" },
        primary: { DEFAULT: "#4f46e5", soft: "#eef2ff", hover: "#4338ca" },
        ok: { DEFAULT: "#10b981", 50: "#ecfdf5" },
        info: { DEFAULT: "#3b82f6", 50: "#eff6ff", 100: "#dbeafe" },
        warn: { DEFAULT: "#f59e0b", 50: "#fffbeb" },
        danger: { DEFAULT: "#ef4444", 50: "#fef2f2", 200: "#fecaca" },
        violet: { DEFAULT: "#8b5cf6", 50: "#f5f3ff", 500: "#8b5cf6" },
        cyan: { DEFAULT: "#06b6d4", 50: "#ecfeff" },
        side: { DEFAULT: "#111827", hover: "#1f2937" },
        cat: { base: "#6b7280", model: "#3b82f6", tool: "#10b981", ctrl: "#f59e0b" },
      },
      borderRadius: { DEFAULT: "10px", sm: "8px" },
      boxShadow: { card: "0 1px 3px rgba(16,24,40,.08)" },
      fontFamily: {
        sans: ['-apple-system', 'BlinkMacSystemFont', '"Segoe UI"', '"PingFang SC"', '"Microsoft YaHei"', 'sans-serif'],
        mono: ['SFMono-Regular', 'ui-monospace', 'Menlo', 'Consolas', 'monospace'],
      },
    },
  },
  plugins: [],
};
