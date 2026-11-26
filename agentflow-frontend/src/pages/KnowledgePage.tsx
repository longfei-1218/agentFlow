import { useEffect, useMemo, useState } from "react";
import { Database, FileText, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { knowledgeApi, type KBDocument, type KBSearchResult, type KnowledgeBase } from "@/api/knowledge";
import { useKnowledgeStore } from "@/store/knowledgeStore";

export function KnowledgePage() {
  const kbs = useKnowledgeStore((s) => s.kbs);
  const loading = useKnowledgeStore((s) => s.loading);
  const storeError = useKnowledgeStore((s) => s.error);
  const load = useKnowledgeStore((s) => s.load);

  const [selectedId, setSelectedId] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [newName, setNewName] = useState("");
  const [newSize, setNewSize] = useState(400);
  const [newOverlap, setNewOverlap] = useState(50);

  const [docs, setDocs] = useState<KBDocument[]>([]);
  const [docTitle, setDocTitle] = useState("");
  const [docContent, setDocContent] = useState("");
  const [docBusy, setDocBusy] = useState(false);

  const [query, setQuery] = useState("");
  const [topK, setTopK] = useState(4);
  const [rerank, setRerank] = useState(false);
  const [searching, setSearching] = useState(false);
  const [searchResult, setSearchResult] = useState<KBSearchResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(
    () => kbs.find((kb) => kb.id === selectedId) ?? null,
    [kbs, selectedId],
  );

  useEffect(() => {
    void load(true);
  }, [load]);

  const loadDocs = async (kbId: string) => {
    try {
      setDocs(await knowledgeApi.documents(kbId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "文档加载失败");
    }
  };

  const selectKb = (kb: KnowledgeBase) => {
    setSelectedId(kb.id);
    setSearchResult(null);
    setError(null);
    void loadDocs(kb.id);
  };

  const createKb = async () => {
    setError(null);
    if (!newName.trim()) {
      setError("知识库名称必填");
      return;
    }
    try {
      const kb = await knowledgeApi.create({
        name: newName.trim(),
        chunkSize: newSize,
        overlap: newOverlap,
      });
      setShowCreate(false);
      setNewName("");
      await load(true);
      selectKb(kb);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建失败");
    }
  };

  const removeKb = async (kb: KnowledgeBase) => {
    if (!window.confirm(`删除知识库 ${kb.name}？其中的文档与切片会一起删除。`)) return;
    try {
      await knowledgeApi.remove(kb.id);
      if (selectedId === kb.id) {
        setSelectedId("");
        setDocs([]);
        setSearchResult(null);
      }
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除失败");
    }
  };

  const addDoc = async () => {
    if (!selected) return;
    setError(null);
    if (!docContent.trim()) {
      setError("文档内容不能为空");
      return;
    }
    setDocBusy(true);
    try {
      await knowledgeApi.addDocument(selected.id, docTitle.trim(), docContent);
      setDocTitle("");
      setDocContent("");
      await loadDocs(selected.id);
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "添加文档失败");
    } finally {
      setDocBusy(false);
    }
  };

  const removeDoc = async (doc: KBDocument) => {
    if (!selected) return;
    try {
      await knowledgeApi.removeDocument(selected.id, doc.id);
      await loadDocs(selected.id);
      await load(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "删除文档失败");
    }
  };

  const runSearch = async () => {
    if (!selected || !query.trim()) return;
    setSearching(true);
    setError(null);
    setSearchResult(null);
    try {
      setSearchResult(await knowledgeApi.search(selected.id, query.trim(), topK, rerank));
    } catch (err) {
      setError(err instanceof Error ? err.message : "检索失败");
    } finally {
      setSearching(false);
    }
  };

  return (
    <div className="h-full overflow-y-auto p-6">
      <div className="flex items-start gap-3">
        <div>
          <h1 className="text-[20px] font-semibold">知识库</h1>
          <p className="text-[12px] text-ink-3 mt-1">
            本地 BM25 检索（中文按字符 bigram 切），不依赖 embedding 服务；画布 knowledge 节点会把命中片段拼成
            <span className="font-mono"> context </span>注入下游。
          </p>
        </div>
        <div className="ml-auto flex items-center gap-2">
          <button className="btn" onClick={() => void load(true)}>
            <RefreshCw size={13} className="inline mr-1 -mt-0.5" />刷新
          </button>
          <button className="btn-primary" onClick={() => setShowCreate((value) => !value)}>
            <Plus size={13} className="inline mr-1 -mt-0.5" />新建知识库
          </button>
        </div>
      </div>

      {(error || storeError) && (
        <div className="mt-3 border border-danger/30 bg-danger-50 rounded-sm px-3 py-2 text-[12px] text-danger">
          {error || storeError}
        </div>
      )}

      {showCreate && (
        <section className="card p-3 mt-4 flex flex-wrap items-end gap-2">
          <label className="block flex-1 min-w-[160px]">
            <span className="block mb-1 text-[12px] text-ink-2">名称</span>
            <input className="field" value={newName} onChange={(e) => setNewName(e.target.value)} placeholder="如 售后知识库" />
          </label>
          <label className="block">
            <span className="block mb-1 text-[12px] text-ink-2">Chunk 字数</span>
            <input type="number" className="field !w-24" min={50} max={2000} value={newSize} onChange={(e) => setNewSize(Number(e.target.value))} />
          </label>
          <label className="block">
            <span className="block mb-1 text-[12px] text-ink-2">Overlap</span>
            <input type="number" className="field !w-24" min={0} max={500} value={newOverlap} onChange={(e) => setNewOverlap(Number(e.target.value))} />
          </label>
          <button className="btn-primary" onClick={() => void createKb()}>创建</button>
          <button className="btn" onClick={() => setShowCreate(false)}>取消</button>
        </section>
      )}

      <div className="grid grid-cols-[minmax(0,1fr)_minmax(0,1.25fr)] gap-4 mt-4">
        <section className="card overflow-hidden self-start">
          <div className="flex items-center gap-2 px-4 py-2.5 border-b border-line">
            <Database size={15} className="text-ok" />
            <span className="font-semibold text-[13px]">知识库列表</span>
            <span className="badge badge-gray">{kbs.length}</span>
            {loading && <span className="text-[11px] text-ink-3">加载中…</span>}
          </div>

          {kbs.length === 0 ? (
            <div className="py-16 text-center text-[12px] text-ink-3 leading-relaxed">
              暂无知识库<br />
              <span className="text-[11px]">点右上「新建知识库」→ 添加文档 → 就能在 knowledge 节点里召回</span>
            </div>
          ) : (
            <table className="w-full text-[12px]">
              <thead className="bg-slate-50 text-ink-3">
                <tr>
                  {["名称", "文档", "切片", "chunk / overlap", "操作"].map((head) => (
                    <th key={head} className="text-left px-3 py-1.5 font-medium whitespace-nowrap">{head}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {kbs.map((kb) => (
                  <tr
                    key={kb.id}
                    className={`border-t border-line cursor-pointer ${selectedId === kb.id ? "bg-primary-soft" : ""}`}
                    onClick={() => selectKb(kb)}
                  >
                    <td className="px-3 py-2">
                      <div className="font-mono text-ink">{kb.name}</div>
                      <div className="text-[10px] text-ink-3 font-mono">{kb.id}</div>
                    </td>
                    <td className="px-3 py-2">{kb.docCount}</td>
                    <td className="px-3 py-2">{kb.chunkCount}</td>
                    <td className="px-3 py-2 text-ink-2 whitespace-nowrap">{kb.chunkSize} / {kb.overlap}</td>
                    <td className="px-3 py-2">
                      <button
                        className="text-danger hover:underline"
                        onClick={(event) => {
                          event.stopPropagation();
                          void removeKb(kb);
                        }}
                      >
                        <Trash2 size={12} className="inline -mt-0.5" />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>

        <section className="card p-4">
          {selected ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <FileText size={15} className="text-info" />
                <span className="font-semibold text-[13px]">{selected.name}</span>
                <span className="badge badge-blue">{selected.chunkCount} chunks</span>
                <span className="text-[11px] text-ink-3 ml-auto font-mono">{selected.collection}</span>
              </div>

              <div>
                <div className="text-[12px] text-ink-2 mb-1.5">添加文档</div>
                <input className="field mb-2" value={docTitle} onChange={(e) => setDocTitle(e.target.value)} placeholder="标题（留空自动生成）" />
                <textarea
                  className="field min-h-[96px]"
                  value={docContent}
                  onChange={(e) => setDocContent(e.target.value)}
                  placeholder="粘贴文档内容：按句切块，超过 chunk 字数自动分包"
                />
                <div className="flex items-center gap-2 mt-2">
                  <span className="text-[11px] text-ink-3">当前 {docContent.length} 字</span>
                  <button className="btn-primary ml-auto" disabled={docBusy} onClick={() => void addDoc()}>
                    添加并切块
                  </button>
                </div>
              </div>

              <div>
                <div className="flex items-center gap-2 mb-1.5">
                  <span className="text-[12px] text-ink-2">文档</span>
                  <span className="badge badge-gray">{docs.length}</span>
                </div>
                {docs.length === 0 ? (
                  <div className="border border-dashed border-line rounded-sm py-6 text-center text-[11px] text-ink-3">
                    还没有文档
                  </div>
                ) : (
                  <div className="border border-line rounded-sm divide-y divide-line max-h-[200px] overflow-y-auto">
                    {docs.map((doc) => (
                      <div key={doc.id} className="flex items-center gap-2 px-2.5 py-1.5 text-[12px]">
                        <span className="truncate flex-1">{doc.title}</span>
                        <span className="text-[11px] text-ink-3 whitespace-nowrap">{doc.chunkCount} 块</span>
                        <button className="text-danger hover:underline" onClick={() => void removeDoc(doc)}>
                          <Trash2 size={12} />
                        </button>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="border-t border-line pt-3">
                <div className="flex items-center gap-2 mb-2">
                  <Search size={15} className="text-info" />
                  <span className="font-semibold text-[13px]">召回测试</span>
                  <span className="text-[11px] text-ink-3 ml-auto">与 knowledge 节点同一套检索</span>
                </div>
                <textarea
                  className="field min-h-[64px]"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="输入问题，如「退款多久到账」"
                />
                <div className="flex items-center gap-2 mt-2">
                  <input
                    type="number"
                    className="field !w-20"
                    min={1}
                    max={20}
                    value={topK}
                    onChange={(e) => setTopK(Number(e.target.value))}
                  />
                  <label className="flex items-center gap-1 text-[12px] text-ink-2">
                    <input type="checkbox" className="w-3.5 h-3.5 accent-primary" checked={rerank} onChange={(e) => setRerank(e.target.checked)} />
                    rerank（MMR 去冗余）
                  </label>
                  <button className="btn-primary ml-auto" disabled={searching || !query.trim()} onClick={() => void runSearch()}>
                    {searching ? "检索中…" : "检索"}
                  </button>
                </div>

                {searchResult && (
                  <div className="mt-3 space-y-2">
                    <div className="text-[11px] text-ink-3">
                      命中 {searchResult.hits.length} / {searchResult.totalChunks} 块 · {searchResult.tookMs} ms ·
                      engine {String(searchResult.extra?.engine ?? "")}
                    </div>
                    {searchResult.hint && (
                      <div className="border border-warn/30 bg-warn-50 rounded-sm px-3 py-2 text-[11px] text-warn">
                        {searchResult.hint}
                      </div>
                    )}
                    {searchResult.hits.map((hit, index) => (
                      <div key={`${hit.docId}-${hit.seq}`} className="border border-line rounded-sm px-3 py-2">
                        <div className="flex items-center gap-2 text-[11px] text-ink-3">
                          <span className="text-ink font-semibold">[{index + 1}] {hit.title}</span>
                          <span className="font-mono">#chunk{hit.seq}</span>
                          <span className="ml-auto">score {hit.score}</span>
                        </div>
                        <div className="mt-1 text-[12px] text-ink-2 leading-relaxed whitespace-pre-wrap">{hit.text}</div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="py-16 text-center text-[12px] text-ink-3 leading-relaxed">
              左侧选一个知识库：添加文档 → 召回测试 → 在画布 knowledge 节点里写它的 kb_id。
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
