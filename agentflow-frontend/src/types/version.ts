/** R6.0 版本管理：与后端 app/models/version.py 对齐（API 层 camelCase）。 */
export type VersionKind = "agent" | "flow";

export interface CodeMeta {
  commit?: string | null;
  branch?: string | null;
  dirty?: boolean;
}

export interface ResourceFingerprint {
  id: string;
  name?: string;
  alias?: string;
  fingerprint?: string;
  updatedAt?: string | null;
  docCount?: number;
  chunkCount?: number;
  tools?: string[];
  missing?: boolean;
}

export interface AgentRef {
  nodeId: string;
  agentId: string;
  name?: string;
  version: number;
  configHash?: string | null;
  baseline?: boolean;
}

export interface VersionManifest {
  schemaVersion?: number;
  kind?: VersionKind;
  resourceId?: string;
  version?: number;
  publishedAt?: string;
  configHash?: string;
  bundleHash?: string;
  code?: CodeMeta;
  llm?: { model?: string; temperature?: number | null };
  agentRefs?: AgentRef[];
  resources?: {
    tools?: ResourceFingerprint[];
    mcp?: ResourceFingerprint[];
    knowledge?: ResourceFingerprint[];
  };
}

export interface VersionSummary {
  id: string;
  kind: VersionKind;
  resourceId: string;
  version: number;
  configHash: string;
  bundleHash: string;
  codeCommit: string | null;
  codeDirty: boolean;
  /** 发布时必填的版本名；老版本行为空，展示时回退到 vN */
  name: string;
  note: string;
  restoredFrom: number | null;
  createdAt: string;
  manifest: VersionManifest;
}

/** snapshot 是该版本的完整配置快照（camelCase），用于排查当时到底配了什么。 */
export interface VersionDetail extends VersionSummary {
  snapshot: Record<string, unknown>;
}

export interface PublishState {
  publishedVersion: number;
  publishedHash: string | null;
  draftHash: string | null;
  ahead: boolean;
  unpublished: boolean;
  versionCount: number;
  /** 历史最大版本号：回滚后指针可能小于它 */
  latestVersion: number;
  lastPublishedAt: string | null;
}

export interface ResourceVersionState {
  kind: VersionKind;
  id: string;
  name: string;
  publish: PublishState;
}

export function kindPath(kind: VersionKind): string {
  return kind === "agent" ? "agents" : "flows";
}
