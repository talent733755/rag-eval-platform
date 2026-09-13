"use client";

import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { StatusBadge } from "@/components/ui/status-badge";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

type Api = ReturnType<typeof createApiClient>;
type Member = Awaited<ReturnType<Api["listProjectMembers"]>>[number];

export function MembersWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [role, setRole] = useState<"admin" | "editor" | "viewer">("viewer");
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const load = useCallback(async () => {
    if (!projectId) return;
    try { setMembers(await client.listProjectMembers(projectId)); setState("ready"); } catch (reason: unknown) { setState("error"); setError(reason instanceof Error ? reason.message : "成员加载失败"); }
  }, [client, projectId]);

  useEffect(() => { void load(); }, [load]);

  if (!projectId) return <EmptyState title="项目与成员" description="请先选择一个项目，再管理成员角色。" actionLabel="返回工作台" actionHref="/" />;
  const activeProjectId = projectId;

  async function updateRole(member: Member, nextRole: "admin" | "editor" | "viewer") {
    setBusyId(member.id); setError(null);
    try { const updated = await client.updateProjectMember(activeProjectId, member.id, { role: nextRole }); setMembers((current) => current.map((item) => item.id === updated.id ? updated : item)); } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "角色更新失败"); } finally { setBusyId(null); }
  }

  async function remove(member: Member) {
    if (!window.confirm("确定移除该项目成员吗？")) return;
    setBusyId(member.id); setError(null);
    try { await client.removeProjectMember(activeProjectId, member.id); setMembers((current) => current.filter((item) => item.id !== member.id)); } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "成员移除失败"); } finally { setBusyId(null); }
  }

  async function invite() {
    if (!email.trim()) return;
    setBusyId("invite"); setError(null);
    try { await client.inviteProjectMember(activeProjectId, { email: email.trim(), role }); setEmail(""); } catch (reason: unknown) { setError(reason instanceof Error ? reason.message : "成员邀请失败"); } finally { setBusyId(null); }
  }

  return <div className="mx-auto max-w-screen-2xl space-y-6"><div><p className="text-sm font-medium text-primary">项目设置</p><h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">项目与成员</h1><p className="mt-2 text-sm text-muted">成员角色由 API 在每次请求中重新校验，移除最后一名管理员会被拒绝。</p></div>{error && <p className="text-sm text-danger-foreground" role="alert">{error}</p>}<section className="rounded-lg border border-border bg-surface p-4"><h2 className="text-base font-semibold text-text">邀请成员</h2><div className="mt-3 flex flex-col gap-2 sm:flex-row"><input className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="成员邮箱" value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" type="email" /><select className="rounded-md border border-border bg-canvas px-3 py-2 text-text" aria-label="邀请角色" value={role} onChange={(event) => setRole(event.target.value as typeof role)}><option value="viewer">查看者</option><option value="editor">编辑者</option><option value="admin">管理员</option></select><button type="button" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white disabled:opacity-50" disabled={!email.trim() || busyId === "invite"} onClick={() => void invite()}>邀请</button></div></section><section className="rounded-lg border border-border bg-surface p-4"><h2 className="text-base font-semibold text-text">当前成员</h2>{state === "loading" && <p className="mt-4 text-sm text-muted" role="status">正在加载成员…</p>}{state === "error" && <p className="mt-4 text-sm text-danger-foreground" role="alert">{error}</p>}{state === "ready" && <div className="mt-4 overflow-x-auto"><table className="w-full min-w-[720px] text-left text-sm"><thead className="border-b border-border text-xs text-muted"><tr><th className="px-3 py-3" scope="col">用户</th><th className="px-3 py-3" scope="col">角色</th><th className="px-3 py-3" scope="col">操作</th></tr></thead><tbody className="divide-y divide-border">{members.map((member) => <tr key={member.id}><th className="px-3 py-4 font-mono text-xs font-medium text-text" scope="row">{member.user_id}</th><td className="px-3 py-4"><select aria-label={`成员 ${member.user_id} 角色`} className="rounded-md border border-border bg-canvas px-2 py-1 text-text" value={member.role} disabled={busyId === member.id} onChange={(event) => void updateRole(member, event.target.value as typeof role)}><option value="viewer">查看者</option><option value="editor">编辑者</option><option value="admin">管理员</option></select></td><td className="px-3 py-4"><button type="button" className="rounded-md border border-danger px-2 py-1 text-xs text-danger-foreground disabled:opacity-50" disabled={busyId === member.id} onClick={() => void remove(member)}>移除</button>{member.role === "admin" && <span className="ml-2"><StatusBadge status="info">管理员</StatusBadge></span>}</td></tr>)}</tbody></table></div>}</section></div>;
}
