import { Database, Search } from "lucide-react";

export function KnowledgePage() {
  return (
    <div className="h-full overflow-y-auto p-6">
      <h1 className="text-[20px] font-semibold">知识库</h1>
      <p className="text-[12px] text-ink-3 mt-1 mb-5">上传文档完成分块与向量化，在画布的 knowledge 节点中召回上下文。</p>

      <div className="grid grid-cols-[1fr_320px] gap-4">
        <section className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Database size={16} className="text-ok" />
            <span className="font-semibold text-[14px]">知识库列表</span>
            <span className="badge badge-green ml-auto">P3</span>
          </div>
          <div className="border border-dashed border-line rounded-sm py-16 text-center text-[12px] text-ink-3">
            暂无知识库<br />
            <span className="text-[11px]">chunk_size / overlap / embedding_model 可配置</span>
          </div>
        </section>

        <section className="card p-4">
          <div className="flex items-center gap-2 mb-3">
            <Search size={16} className="text-info" />
            <span className="font-semibold text-[14px]">召回测试</span>
          </div>
          <textarea className="field min-h-[80px]" placeholder="输入测试问题…" disabled />
          <div className="flex gap-2 mt-2">
            <input className="field w-20" defaultValue="4" disabled />
            <label className="flex items-center gap-1 text-[12px] text-ink-2">
              <input type="checkbox" disabled /> rerank
            </label>
            <button className="btn-primary ml-auto" disabled>检索</button>
          </div>
          <div className="mt-3 text-[11px] text-ink-3 leading-relaxed">
            结果将展示相似度分数、片段与 chunk 来源。
          </div>
        </section>
      </div>
    </div>
  );
}
