"use client";

import { useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/ui/empty-state";
import { ProjectLink } from "@/components/ui/project-link";
import { createApiClient } from "@/lib/api/client";
import { getProjectIdFromSearch, useProjectSearch } from "@/lib/project-context";

type StepState = "done" | "current" | "todo";

type Step = {
  key: string;
  title: string;
  description: string;
  actionLabel: string;
  actionHref: string;
  state: StepState;
  summary: string;
};

export function DashboardWorkspace() {
  const search = useProjectSearch();
  const projectId = getProjectIdFromSearch(search);
  const client = useMemo(() => createApiClient(), []);
  const [steps, setSteps] = useState<Step[]>([]);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  useEffect(() => {
    if (!projectId) return;
    const controller = new AbortController();
    void (async () => {
      try {
        const [documents, datasets, experiments, adapters] = await Promise.all([
          client.listDocuments(projectId, { signal: controller.signal }),
          client.listCandidateDatasets(projectId, { signal: controller.signal }),
          client.listExperiments(projectId, { signal: controller.signal }),
          client.listAdapters(projectId, { signal: controller.signal }),
        ]);

        const docItems = documents.items ?? [];
        const parsedCount = docItems.filter(
          (doc) => doc.latest_version?.parse_status === "succeeded",
        ).length;
        const datasetCount = datasets.length;
        const publishedCount = datasets.filter((dataset) => dataset.status === "published").length;
        const hasAdapter = adapters.length > 0;
        const experimentCount = experiments.length;

        const stepDefs: Array<Omit<Step, "state">> = [
          {
            key: "upload",
            title: "上传文档",
            description: "把知识库文档传上来，系统会自动解析成分片，作为评测的问题来源。",
            actionLabel: "去上传文档",
            actionHref: "/documents",
            summary: docItems.length === 0 ? "还没有文档" : `${docItems.length} 份文档 · ${parsedCount} 份已解析`,
          },
          {
            key: "generate",
            title: "生成评测集",
            description: "从已解析的文档自动生成问答候选，聚成一个可审核的评测集。",
            actionLabel: "去生成评测集",
            actionHref: "/documents",
            summary: datasetCount === 0 ? "还没有评测集" : `${datasetCount} 个评测集`,
          },
          {
            key: "review",
            title: "审核并发布",
            description: "逐条确认候选问题和参考答案，全部接受后发布，发布后才能用于实验。",
            actionLabel: "去审核",
            actionHref: "/review",
            summary: publishedCount === 0 ? "还没有已发布版本" : `${publishedCount} 个已发布版本`,
          },
          {
            key: "run",
            title: "运行实验",
            description: "接入你的 RAG 服务，用已发布的评测集跑一轮评测，查看质量指标。",
            actionLabel: "去运行实验",
            actionHref: "/experiments",
            summary:
              experimentCount === 0
                ? hasAdapter
                  ? "已接入服务，可以开始实验"
                  : "还没有实验（先接入 Pipeline）"
                : `${experimentCount} 个实验`,
          },
        ];

        // Determine current step: the first one that is not yet complete.
        const completion = [
          parsedCount > 0,
          datasetCount > 0,
          publishedCount > 0,
          experimentCount > 0,
        ];
        const firstIncomplete = completion.findIndex((done) => !done);
        const resolved: Step[] = stepDefs.map((step, index) => ({
          ...step,
          state: completion[index]
            ? "done"
            : index === firstIncomplete || firstIncomplete === -1
              ? "current"
              : "todo",
        }));
        setSteps(resolved);
        setState("ready");
      } catch (reason: unknown) {
        if (reason instanceof DOMException && reason.name === "AbortError") return;
        setState("error");
      }
    })();
    return () => controller.abort();
  }, [client, projectId]);

  if (!projectId) {
    return (
      <EmptyState
        title="欢迎使用 RAG 评测平台"
        description="请先在顶部选择一个项目，我们会一步步带你完成第一次评测。"
        actionLabel="选择项目后从这里开始"
        actionHref="/"
      />
    );
  }

  return (
    <div className="mx-auto max-w-screen-lg space-y-8">
      <div>
        <p className="text-sm font-medium text-primary">快速上手</p>
        <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">
          四步完成一次 RAG 评测
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted">
          按下面的顺序操作即可。每一步完成后会自动打勾，并高亮你的下一步。
        </p>
      </div>

      {state === "error" && (
        <p className="rounded-md border border-danger bg-canvas px-4 py-3 text-sm text-danger-foreground" role="alert">
          工作台数据加载失败，请刷新重试。
        </p>
      )}

      <ol className="space-y-4" aria-label="上手步骤">
        {(state === "loading" ? [] : steps).map((step, index) => {
          const isDone = step.state === "done";
          const isCurrent = step.state === "current";
          return (
            <li
              key={step.key}
              className={[
                "flex gap-4 rounded-lg border p-5 transition-colors",
                isCurrent
                  ? "border-primary bg-surface shadow-sm shadow-primary/10"
                  : "border-border bg-surface",
              ].join(" ")}
            >
              <div
                aria-hidden
                className={[
                  "flex h-9 w-9 shrink-0 items-center justify-center rounded-full text-sm font-semibold",
                  isDone
                    ? "bg-success text-success-foreground"
                    : isCurrent
                      ? "bg-primary text-white"
                      : "bg-canvas text-muted",
                ].join(" ")}
              >
                {isDone ? "✓" : index + 1}
              </div>
              <div className="min-w-0 flex-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <h2 className="text-base font-semibold text-text">{step.title}</h2>
                  {isCurrent && (
                    <span className="rounded-full bg-primary/10 px-2 py-0.5 text-xs font-medium text-primary">
                      当前步骤
                    </span>
                  )}
                  {isDone && <span className="text-xs font-medium text-success-foreground">已完成</span>}
                </div>
                <p className="mt-1 text-sm text-muted">{step.description}</p>
                <p className="mt-2 text-xs text-muted">{step.summary}</p>
                {(isCurrent || (!isDone && index === 0)) && (
                  <ProjectLink
                    href={step.actionHref}
                    className="mt-3 inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-white"
                  >
                    {step.actionLabel}
                  </ProjectLink>
                )}
              </div>
            </li>
          );
        })}
        {state === "loading" && (
          <li className="rounded-lg border border-border bg-surface p-6 text-sm text-muted" role="status">
            正在分析你的项目进度…
          </li>
        )}
      </ol>
    </div>
  );
}
