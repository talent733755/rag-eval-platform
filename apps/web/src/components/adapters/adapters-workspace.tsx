"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

type Api = ReturnType<typeof createApiClient>;
type Adapter = Awaited<ReturnType<Api["listAdapters"]>>[number];

const EMPTY_FORM = { name: "", endpoint: "", credentialRef: "", enabled: false };

export function AdaptersWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [adapters, setAdapters] = useState<Adapter[]>([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [editing, setEditing] = useState<Adapter | null>(null);
  const [state, setState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!projectId) return;
    setState("loading");
    try {
      setAdapters(await client.listAdapters(projectId, { signal }));
      setState("ready");
    } catch (reason: unknown) {
      if (reason instanceof DOMException && reason.name === "AbortError") return;
      setError(reason instanceof Error ? reason.message : "Adapter 加载失败");
      setState("error");
    }
  }, [client, projectId]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (!projectId) {
    return <EmptyState title="Pipeline 接入" description="请先选择一个项目，再配置 RAG Pipeline Adapter。" actionLabel="返回工作台" actionHref="/" />;
  }
  const activeProjectId = projectId;

  function beginEdit(adapter: Adapter) {
    setEditing(adapter);
    setForm({ name: adapter.name, endpoint: adapter.endpoint ?? "", credentialRef: adapter.credential_ref ?? "", enabled: adapter.enabled });
    setError(null);
  }

  function resetForm() {
    setEditing(null);
    setForm(EMPTY_FORM);
  }

  async function save() {
    if (!form.name.trim() || !form.endpoint.trim()) return;
    setError(null);
    try {
      if (editing) {
        await client.updateAdapter(activeProjectId, editing.id, {
          name: form.name.trim(),
          endpoint: form.endpoint.trim(),
          credential_ref: form.credentialRef.trim() || null,
          enabled: form.enabled,
        });
      } else {
        await client.createAdapter(activeProjectId, {
          name: form.name.trim(),
          kind: "http",
          endpoint: form.endpoint.trim(),
          credential_ref: form.credentialRef.trim() || null,
          adapter_version: "adapter-v1",
          trace_level: "minimal",
          timeout_seconds: 30,
          retry_count: 0,
          enabled: false,
        });
      }
      resetForm();
      await load();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : editing ? "Adapter 更新失败" : "Adapter 创建失败");
    }
  }

  async function test(adapter: Adapter) {
    setBusyId(adapter.id);
    setError(null);
    try {
      const result = await client.testAdapter(activeProjectId, adapter.id);
      setAdapters((current) => current.map((item) => item.id === result.id ? result : item));
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "连接测试失败");
      await load();
    } finally {
      setBusyId(null);
    }
  }

  async function remove(adapter: Adapter) {
    if (!window.confirm(`确认删除 Adapter“${adapter.name}”吗？`)) return;
    setBusyId(adapter.id);
    setError(null);
    try {
      await client.deleteAdapter(activeProjectId, adapter.id);
      setAdapters((current) => current.filter((item) => item.id !== adapter.id));
      if (editing?.id === adapter.id) resetForm();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "Adapter 删除失败");
    } finally {
      setBusyId(null);
    }
  }

  return <div className="mx-auto max-w-screen-2xl space-y-6">
    <div>
      <p className="text-sm font-medium text-primary">运行接入</p>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">Pipeline 接入</h1>
      <p className="mt-2 text-sm text-muted">凭据只通过服务端环境变量引用，页面和 API 不保存明文 Token。连接测试会向 Adapter 发送一次受控的 adapter-v1 请求。</p>
    </div>
    {error && <p className="text-sm text-danger-foreground" role="alert">{error}</p>}
    <section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="adapter-create-heading">
      <div className="flex items-center justify-between gap-3">
        <h2 id="adapter-create-heading" className="text-base font-semibold text-text">{editing ? "编辑 HTTP Adapter" : "添加 HTTP Adapter"}</h2>
        {editing && <button type="button" className="text-sm text-muted underline" onClick={resetForm}>取消编辑</button>}
      </div>
      <div className="mt-4 grid gap-3 md:grid-cols-4">
        <input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="Adapter 名称" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} placeholder="名称" />
        <input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="Adapter 地址" value={form.endpoint} onChange={(event) => setForm({ ...form, endpoint: event.target.value })} placeholder="https://adapter.example.test" />
        <input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="凭据引用" value={form.credentialRef} onChange={(event) => setForm({ ...form, credentialRef: event.target.value })} placeholder="环境变量名（可选）" />
        <div className="flex items-center gap-3">
          {editing && <label className="flex items-center gap-2 text-sm text-muted"><input type="checkbox" checked={form.enabled} onChange={(event) => setForm({ ...form, enabled: event.target.checked })} />启用</label>}
          <button type="button" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={!form.name.trim() || !form.endpoint.trim()} onClick={() => void save()}>{editing ? "保存修改" : "保存配置"}</button>
        </div>
      </div>
    </section>
    <section className="rounded-lg border border-border bg-surface p-4" aria-labelledby="adapter-list-heading">
      <h2 id="adapter-list-heading" className="text-base font-semibold text-text">已配置 Adapter</h2>
      {state === "loading" && <p className="mt-6 text-sm text-muted" role="status">正在加载…</p>}
      {state === "ready" && adapters.length === 0 && <p className="mt-6 text-sm text-muted">还没有配置 Adapter。</p>}
      {adapters.length > 0 && <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[900px] text-left text-sm"><thead className="border-b border-border text-xs text-muted"><tr><th className="px-3 py-3" scope="col">名称</th><th className="px-3 py-3" scope="col">类型/版本</th><th className="px-3 py-3" scope="col">启用状态</th><th className="px-3 py-3" scope="col">连接状态</th><th className="px-3 py-3" scope="col">凭据引用</th><th className="px-3 py-3" scope="col">操作</th></tr></thead><tbody className="divide-y divide-border">{adapters.map((adapter) => <tr key={adapter.id}><th className="px-3 py-4 font-medium text-text" scope="row">{adapter.name}</th><td className="px-3 py-4 text-muted">{adapter.kind} · {adapter.adapter_version}</td><td className="px-3 py-4"><StatusBadge status={adapter.enabled ? "success" : "neutral"}>{adapter.enabled ? "已启用" : "未启用"}</StatusBadge></td><td className="px-3 py-4"><StatusBadge status={adapter.last_test_status === "succeeded" ? "success" : adapter.last_test_status === "failed" ? "failed" : "neutral"}>{adapter.last_test_status === "succeeded" ? "已连接" : adapter.last_test_status === "failed" ? "失败" : "未测试"}</StatusBadge></td><td className="px-3 py-4 font-mono text-xs text-muted">{adapter.credential_ref ?? "—"}</td><td className="px-3 py-4"><div className="flex gap-2"><button type="button" className="rounded-md border border-border px-2 py-1 text-xs text-text disabled:opacity-50" disabled={busyId === adapter.id} onClick={() => beginEdit(adapter)}>编辑</button><button type="button" className="rounded-md border border-border px-2 py-1 text-xs text-text disabled:opacity-50" disabled={busyId === adapter.id} onClick={() => void test(adapter)}>测试连接</button><button type="button" className="rounded-md border border-danger px-2 py-1 text-xs text-danger-foreground disabled:opacity-50" disabled={busyId === adapter.id} onClick={() => void remove(adapter)}>删除</button></div></td></tr>)}</tbody></table></div>}
    </section>
  </div>;
}
