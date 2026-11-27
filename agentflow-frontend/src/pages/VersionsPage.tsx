import { useEffect, useMemo, useState } from "react";
import { AlertTriangle, GitBranch, History, RefreshCw, RotateCcw } from "lucide-react";
import { useSearchParams } from "react-router-dom";
import { agentsApi } from "@/api/agents";
import { flowsApi } from "@/api/flows";
import { versionsApi } from "@/api/versions";
import { ApiError } from "@/api/client";
import { PublishDialog } from "@/components/versions/PublishDialog";
import { VersionSnapshot } from "@/components/versions/VersionSnapshot";
import type {
  ResourceVersionState,
  ResourceFingerprint,
  VersionDetail,
  VersionKind,
  VersionManifest,
} from "@/types/version";

const KIND_LABEL: Record<VersionKind, string> = { agent: "Agent", flow: "流程" };

function when(value?: string | null): string {
  if (!value) return "—";
  return new Date(value).toLocaleString("zh-CN", { hour12: false });
}

function StateChips({ state }: { state: ResourceVersionState }) {
  const publish = state.publish;
  return (
    <div className="flex items-center gap-1.5 flex-wrap">
      {publish.unpublished ? (
        <span className="badge-gray">未发布</span>
      ) : (
        <span className="badge-blue">发布 v{publish.publishedVersion}</span>
      )}
      {publish.ahead && <span className="badge-yellow">有未发布改动</span>}
      {!publish.unpublished && publish.latestVersion > publish.publishedVersion && (
        <span className="badge-gray" title="历史版本最大号大于当前发布指针：说明回滚过">
          已回滚 · 最高 v{publish.latestVersion}
        </span>
      )}
    </div>
  );
}

function ManifestPanel({ detail }: { detail: VersionDetail }) {
  const manifest: VersionManifest = detail.manifest ?? {};
  const refs = manifest.agentRefs ?? [];
  const resources = manifest.resources ?? {};
  const groups: { label: string; items: ResourceFingerprint[] }[] = [
    { label: "工具", items: resources.tools ?? [] },
    { label: "MCP", items: resources.mcp ?? [] },
    { label: "知识库", items: resources.knowledge ?? [] },
  ];

  return (
    <div className="card p-3 space-y-3">
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-[12px]">
        <div>
          <div className="text-[11px] text-ink-3">配置指纹</div>
          <div className="font-mono text-ink">{detail.configHash}</div>
        </div>
        <div>
          <div className="text-[11px] text-ink-3">Bundle 指纹</div>
          <div className="font-mono text-ink">{detail.bundleHash}</div>
        </div>
        <div>
          <div className="text-[11px] text-ink-3">代码 commit</div>
          <div className="font-mono">
            {manifest.code?.commit ?? "未知"}
            {manifest.code?.branch ? <span className="text-ink-3"> · {manifest.code.branch}</span> : null}
            {detail.codeDirty && <span className="badge-red ml-2">工作区脏</span>}
          </div>
        </div>
        <div>
          <div className="text-[11px] text-ink-3">模型</div>
          <div>{manifest.llm?.model || "跟随全局默认"}</div>
        </div>
        <div className="col-span-2">
          <div className="text-[11px] text-ink-3">版本名</div>
          <div className="text-ink">{detail.name || `v${detail.version}`}</div>
        </div>
        <div>
          <div className="text-[11px] text-ink-3">发布指针</div>
          <div>v{detail.version}</div>
        </div>
        <div>
          <div className="text-[11px] text-ink-3">发布时间</div>
          <div>{when(detail.createdAt)}</div>
        </div>
      </div>

      {detail.note && (
        <div className="text-[12px] text-ink-2 border-t border-line pt-2">
          <span className="text-[11px] text-ink-3 mr-2">发布说明</span>
          {detail.note}
        </div>
      )}

      {refs.length > 0 && (
        <div className="border-t border-line pt-2">
          <div className="text-[11px] text-ink-3 mb-1">绑定的 Agent 版本</div>
          <table className="w-full text-[12px]">
            <thead>
              <tr className="text-ink-3 text-left">
                <th className="py-1 font-normal">节点</th>
                <th className="py-1 font-normal">Agent</th>
                <th className="py-1 font-normal">版本</th>
                <th className="py-1 font-normal">配置指纹</th>
              </tr>
            </thead>
            <tbody>
              {refs.map((ref) => (
                <tr key={ref.nodeId} className="border-t border-line">
                  <td className="py-1 font-mono">{ref.nodeId}</td>
                  <td className="py-1">
                    {ref.name || "—"}
                    <span className="text-ink-3 font-mono ml-1">{ref.agentId}</span>
                  </td>
                  <td className="py-1">
                    v{ref.version}
                    {ref.baseline && <span className="badge-gray ml-1">基线</span>}
                  </td>
                  <td className="py-1 font-mono text-ink-2">{ref.configHash || "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {groups.some((group) => group.items.length > 0) && (
        <div className="border-t border-line pt-2">
          <div className="text-[11px] text-ink-3 mb-1">资源指纹</div>
          <div className="flex flex-wrap gap-1.5">
            {groups.flatMap((group) =>
              group.items.map((item) => (
                <span key={`${group.label}-${item.id}`} className="chip" title={`${group.label} ${item.id}`}>
                  {group.label}·{item.name || item.alias || item.id}
                  <span className="font-mono text-ink-3 ml-1">
                    {item.missing ? "缺失" : item.fingerprint}
                  </span>
                </span>
              )),
            )}
          </div>
        </div>
      )}
    </div>
  );
}

export function VersionsPage() {
  const [params] = useSearchParams();
  const initialKind: VersionKind = params.get("kind") === "flow" ? "flow" : "agent";
  const initialId = params.get("id");

  const [kind, setKind] = useState<VersionKind>(initialKind);
  const [resources, setResources] = useState<ResourceVersionState[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialId);
  const [versions, setVersions] = useState<VersionDetail[]>([]);
  const [selectedVersion, setSelectedVersion] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [publishOpen, setPublishOpen] = useState(false);

  const loadResources = async () => {
    setLoading(true);
    try {
      const list = await versionsApi.list();
      setResources(list);
      return list;
    } catch (err) {
      setError(err instanceof Error ? err.message : "版本列表加载失败");
      return [];
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void loadResources();
  }, []);

  const current = useMemo(
    () => resources.find((item) => item.kind === kind && item.id === selectedId) ?? null,
    [resources, kind, selectedId],
  );

  const list = useMemo(
    () => resources.filter((item) => item.kind === kind),
    [resources, kind],
  );

  // 切换 tab / 初次加载：自动选中有 URL 指定的资源，否则选第一条
  useEffect(() => {
    if (list.length === 0) return;
    if (selectedId && list.some((item) => item.id === selectedId)) return;
    setSelectedId(list[0].id);
    setSelectedVersion(null);
  }, [list, selectedId]);

  useEffect(() => {
    if (!selectedId) {
      setVersions([]);
      setSelectedVersion(null);
      return;
    }
    let alive = true;
    versionsApi
      .versions(kind, selectedId)
      .then((rows) => {
        if (!alive) return;
        setVersions(rows);
        setSelectedVersion((old) => (old && rows.some((row) => row.version === old) ? old : rows[0]?.version ?? null));
      })
      .catch((err) => {
        if (alive) setError(err instanceof Error ? err.message : "版本读取失败");
      });
    return () => {
      alive = false;
    };
  }, [kind, selectedId]);

  const detail = versions.find((row) => row.version === selectedVersion) ?? null;

  const switchKind = (next: VersionKind) => {
    setKind(next);
    setError(null);
    setNotice(null);
    setRollbackTarget(null);
    setSelectedVersion(null);
    setSelectedId(null);
  };

  const doRollback = async () => {
    if (!selectedId || rollbackTarget === null) return;
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      await versionsApi.rollback(kind, selectedId, rollbackTarget);
      setNotice(`已恢复到 v${rollbackTarget}：发布指针指回该版本，草稿同步回该快照；没有新增版本，也没有改动任何 Agent 版本号。`);
      const list = await loadResources();
      const rows = await versionsApi.versions(kind, selectedId);
      setVersions(rows);
      const state = list.find((item) => item.kind === kind && item.id === selectedId);
      setSelectedVersion(state?.publish.publishedVersion ?? rollbackTarget);
      setRollbackTarget(null);
    } catch (err) {
      if (err instanceof ApiError) {
        setError(`${err.message}${err.detail.length ? `：${err.detail.map((item) => item.message).join("；")}` : ""}`);
      } else {
        setError(err instanceof Error ? err.message : "回滚失败");
      }
    } finally {
      setBusy(false);
    }
  };

  const publishNewVersion = async (name: string, note: string) => {
    if (!current) return;
    setBusy(true);
    setError(null);
    try {
      if (kind === "agent") {
        await agentsApi.publish(current.id, { name, note });
      } else {
        await flowsApi.publish(current.id, { name, note });
      }
      setPublishOpen(false);
      setNotice("已发布新版本，快照与指纹已写入版本记录。");
      await loadResources();
      const rows = await versionsApi.versions(kind, current.id);
      setVersions(rows);
      setSelectedVersion(rows[0]?.version ?? null);
    } catch (err) {
      setPublishOpen(false);
      if (err instanceof ApiError) {
        setError(`${err.message}${err.detail.length ? `：${err.detail.map((item) => item.message).join("；")}` : ""}`);
      } else {
        setError(err instanceof Error ? err.message : "发布失败");
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="h-full flex flex-col">
      <div className="h-[52px] flex-shrink-0 flex items-center gap-3 px-5 bg-white border-b border-line">
        <History size={16} className="text-primary" />
        <span className="text-[14px] font-semibold">版本管理</span>
        <div className="flex gap-1 ml-3">
          {(["agent", "flow"] as VersionKind[]).map((item) => (
            <button
              key={item}
              className={`px-3 py-1.5 rounded-sm text-[12px] ${kind === item ? "bg-primary text-white" : "bg-white border border-line text-ink-2"}`}
              onClick={() => switchKind(item)}
            >
              {KIND_LABEL[item]} 版本
              <span className={`ml-1.5 ${kind === item ? "text-white/70" : "text-ink-3"}`}>
                {resources.filter((row) => row.kind === item).length}
              </span>
            </button>
          ))}
        </div>
        {current && (
          <button className="btn !py-1 ml-auto" onClick={() => setPublishOpen(true)}>
            发布新版本
          </button>
        )}
        <button className={`btn !py-1 ${current ? "" : "ml-auto"}`} onClick={() => void loadResources()} disabled={loading}>
          <RefreshCw size={13} className="inline mr-1 -mt-0.5" />刷新
        </button>
      </div>

      {(error || notice) && (
        <div className={`flex-shrink-0 px-5 py-2 text-[12px] border-b ${error ? "bg-danger-50 border-danger/30 text-danger" : "bg-ok-50 border-ok/30 text-ok"}`}>
          {error ?? notice}
        </div>
      )}

      <div className="flex-1 min-h-0 flex">
        <aside className="w-[300px] flex-shrink-0 border-r border-line bg-white overflow-y-auto">
          {list.length === 0 && (
            <div className="p-4 text-[12px] text-ink-3">
              还没有{KIND_LABEL[kind]}资源。新建后保存即可出现在这里，发布后生成第一个版本。
            </div>
          )}
          {list.map((item) => (
            <button
              key={item.id}
              className={`w-full text-left px-3 py-2.5 border-b border-line hover:bg-slate-50 ${
                item.id === selectedId ? "bg-primary/5 border-l-2 border-l-primary" : ""
              }`}
              onClick={() => {
                setSelectedId(item.id);
                setSelectedVersion(null);
                setRollbackTarget(null);
                setNotice(null);
              }}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="text-[13px] font-medium truncate">{item.name}</span>
                <span className="text-[11px] text-ink-3 flex-shrink-0">{item.publish.versionCount} 版</span>
              </div>
              <div className="mt-1.5 flex items-center gap-1.5 flex-wrap">
                {item.publish.unpublished ? (
                  <span className="badge-gray">未发布</span>
                ) : (
                  <span className="badge-blue">v{item.publish.publishedVersion}</span>
                )}
                {item.publish.ahead && <span className="badge-yellow">草稿领先</span>}
              </div>
            </button>
          ))}
        </aside>

        <main className="flex-1 min-w-0 overflow-y-auto bg-canvas p-4">
          {!current && (
            <div className="text-[12px] text-ink-3">从左侧选择一个{KIND_LABEL[kind]}查看版本历史。</div>
          )}

          {current && (
            <div className="space-y-4">
              <div className="card p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-[15px] font-semibold">{current.name}</div>
                    <div className="text-[11px] text-ink-3 mt-0.5">
                      当前保存内容 → 发布指针 v{current.publish.publishedVersion || 0}
                      {current.publish.ahead ? " · 草稿有未发布改动（运行使用草稿）" : " · 草稿与发布版一致"}
                    </div>
                  </div>
                  <StateChips state={current} />
                </div>
                {current.publish.lastPublishedAt && (
                  <div className="text-[11px] text-ink-3 mt-2">
                    最近发布：{when(current.publish.lastPublishedAt)}
                  </div>
                )}
              </div>

              {versions.length === 0 ? (
                <div className="card p-6 text-center text-[12px] text-ink-3">
                  <GitBranch className="mx-auto mb-2 text-ink-3" size={18} />
                  还没有发布版本。点右上角「发布新版本」生成 v1，之后会记录配置指纹、工具指纹与代码 commit。
                </div>
              ) : (
                <div className="flex gap-4 items-start">
                  <aside className="w-[190px] flex-shrink-0 space-y-1.5">
                    {versions.map((row) => {
                      const isCurrent = row.version === current.publish.publishedVersion;
                      return (
                        <button
                          key={row.id}
                          className={`w-full text-left card px-2.5 py-2 ${row.version === selectedVersion ? "border-primary" : ""}`}
                          onClick={() => setSelectedVersion(row.version)}
                        >
                          <div className="flex items-center gap-1.5">
                            <span className="text-[13px] font-semibold">v{row.version}</span>
                            {isCurrent && <span className="badge-blue">当前</span>}
                            {row.codeDirty && <span className="badge-red">脏</span>}
                          </div>
                          <div className="text-[11px] text-ink-3 mt-0.5">{when(row.createdAt)}</div>
                          {row.name && (
                            <div className="text-[12px] text-ink-2 truncate mt-0.5">{row.name}</div>
                          )}
                          {row.note && <div className="text-[11px] text-ink-3 truncate mt-0.5">{row.note}</div>}
                        </button>
                      );
                    })}
                  </aside>

                  <div className="flex-1 min-w-0 space-y-3">
                    {detail && (
                      <>
                        <ManifestPanel detail={detail} />

                        {rollbackTarget === detail.version ? (
                          <div className="card p-3 border-warn/40 bg-warn-50">
                            <div className="flex items-start gap-2 text-[12px] text-warn">
                              <AlertTriangle size={14} className="mt-0.5" />
                              <div>
                                将把发布指针指回 v{detail.version}，并用该快照覆盖当前草稿。不会新增版本、
                                不会删除 v{detail.version + 1} 及之后的历史，也不会改动任何 Agent 的版本号。
                                运行使用草稿，所以回滚会立刻影响后续运行。
                              </div>
                            </div>
                            <div className="flex gap-2 justify-end mt-2">
                              <button className="btn" onClick={() => setRollbackTarget(null)} disabled={busy}>取消</button>
                              <button className="btn-primary" onClick={() => void doRollback()} disabled={busy}>
                                {busy ? "回滚中…" : `确认恢复到 v${detail.version}`}
                              </button>
                            </div>
                          </div>
                        ) : (
                          <div className="flex items-center gap-2">
                            <button
                              className="btn"
                              onClick={() => setRollbackTarget(detail.version)}
                              disabled={
                                detail.version === current.publish.publishedVersion && !current.publish.ahead
                              }
                              title={
                                detail.version === current.publish.publishedVersion && !current.publish.ahead
                                  ? "当前指针与草稿都已在这个版本"
                                  : "发布指针指回该版本，并把快照写回草稿"
                              }
                            >
                              <RotateCcw size={13} className="inline mr-1 -mt-0.5" />恢复到此版本
                            </button>
                            {detail.version === current.publish.publishedVersion && !current.publish.ahead && (
                              <span className="text-[11px] text-ink-3">当前指针与草稿都已是该版本</span>
                            )}
                          </div>
                        )}

                        <div className="card p-3">
                          <div className="text-[11px] text-ink-3 mb-2">
                            配置快照 · v{detail.version}
                            {detail.name ? ` · ${detail.name}` : ""}
                          </div>
                          <VersionSnapshot detail={detail} />
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}
        </main>
      </div>

      <PublishDialog
        open={publishOpen}
        title={`发布 ${current?.name ?? ""} 新版本`}
        description={
          kind === "flow"
            ? "发布会绑定各 Agent 节点的当前发布版本，并记录工具指纹与代码 commit。"
            : "发布会生成不可变配置快照；运行仍使用当前保存的版本。"
        }
        busy={busy}
        onClose={() => setPublishOpen(false)}
        onConfirm={(name, note) => void publishNewVersion(name, note)}
      />
    </div>
  );
}
