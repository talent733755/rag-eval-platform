"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

type Api = ReturnType<typeof createApiClient>;
type Adapter = Awaited<ReturnType<Api["listAdapters"]>>[number];

export function AdaptersWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [name, setName] = useState("");
  const [endpoint, setEndpoint] = useState("");
  const [credentialRef, setCredentialRef] = useState("");
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(() => {
    if (!projectId) return;
    const controller = new AbortController();
    setState("loading");
    client.listAdapters(projectId, { signal: controller.signal }).then((result) => { setAdapters(result); setState("ready"); }).catch((reason: unknown) => { if (reason instanceof DOMException && reason.name === "AbortError") return; setError(reason instanceof Error ? reason.message : "Adapter 加载失败"); setState("error"); });
    return () => controller.abort();
  }, [client, projectId]);

  useEffect(() => load(), [load]);

  if (!projectId) return <EmptyState title="Pipeline 接入" description="请先选择一个项目，再配置 RAG Pipeline Adapter。" actionLabel="返回工作台" actionHref="/" />;
  const activeProjectId = projectId;

  async function create() {
    if (!name.trim() || !endpoint.trim()) return;
    setError(null);
    try {
      await client.createAdapter(activeProjectId, { name: name.trim(), kind: "http", endpoint: endpoint.trim(), credential_ref: credentialRef.trim() || null, adapter_version: "adapter-v1", trace_level: "minimal", timeout_seconds: 30, retry_count: 0, enabled: false });
      setName(""); setEndpoint(""); setCredentialRef("");
      load();
    } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "Adapter 创建失败"); }
  }

  return <div className="mx-auto max-w-screen-2xl space-y-6"><div><p className="text-sm font-medium text-primary">运行接入</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">Pipeline 接入</h1><p className="mt-2 text-sm text-muted">凭据只通过服务端环境变量引用，页面和 API 不保存明文 Token。</p></div>{error && <p className="text-sm text-danger-foreground" role="alert">{error}</p>}<section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="adapter-create-heading"><h2 id="adapter-create-heading" className="text-base font-semibold text-text">添加 HTTP Adapter</h2><div className="mt-4 grid gap-3 md:grid-cols-3"><input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="Adapter 名称" value={name} onChange={(event) => setName(event.target.value)} placeholder="名称" /><input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="Adapter 地址" value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://adapter.example.test" /><input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="凭据引用" value={credentialRef} onChange={(event) => setCredentialRef(event.target.value)} placeholder="环境变量名（可选）" /><button type="button" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={!name.trim() || !endpoint.trim()} onClick={() => void create()}>保存配置</button></div></section><section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="adapter-list-heading"><h2 id="adapter-list-heading" className="text-base font-semibold text-text">已配置 Adapter</h2>{state === "loading" && <p className="mt-6 text-sm text-muted" role="status">正在加载…</p>}{state === "ready" && adapters.length === 0 && <p className="mt-6 text-sm text-muted">还没有配置 Adapter。</p>}{adapters.length > 0 && <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[680px] text-left text-sm"><thead className="border-b border-border text-xs text-muted"><tr><th className="px-3 py-3" scope="col">名称</th><th className="px-3 py-3" scope="col">类型/版本</th><th className="px-3 py-3" scope="col">状态</th><th className="px-3 py-3" scope="col">凭据引用</th></tr></thead><tbody className="divide-y divide-border">{adapters.map((adapter) => <tr key={adapter.id}><th className="px-3 py-4 font-medium text-text" scope="row">{adapter.name}</th><td className="px-3 py-4 text-muted">{adapter.kind} · {adapter.adapter_version}</td><td className="px-3 py-4"><StatusBadge status={adapter.enabled ? "success" : "neutral"}>{adapter.enabled ? "已启用" : "未启用"}</StatusBadge></td><td className="px-3 py-4 font-mono text-xs text-muted">{adapter.credential_ref ?? "—"}</td></tr>)}</tbody></table></div>}</section></div>;
}
