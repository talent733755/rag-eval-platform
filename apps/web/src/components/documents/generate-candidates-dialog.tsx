"use client";

import { useEffect, useRef, useState } from "react";

import type { createApiClient } from "@/lib/api/client";

type ApiClient = ReturnType<typeof createApiClient>;

type Props = {
  client: ApiClient;
  projectId: string;
  documentId: string;
  documentVersionId: string;
  documentName: string;
  onClose: () => void;
  onGenerated: (message: string) => void;
};

/**
 * Minimal dialog to trigger candidate-dataset generation for one parsed document
 * version. The backend creates/reuses the dataset by name and enqueues a generation
 * job (idempotent via the client's Idempotency-Key). Defaults are deterministic and
 * overridable; the caller stays responsible for the prompt/dataset naming.
 */
export function GenerateCandidatesDialog({
  client,
  projectId,
  documentId,
  documentVersionId,
  documentName,
  onClose,
  onGenerated,
}: Props) {
  const [datasetName, setDatasetName] = useState(documentName.replace(/\.[^.]+$/, "") || "候选评测集");
  const [promptVersion, setPromptVersion] = useState("v1");
  const [randomness, setRandomness] = useState("1");
  const [seed, setSeed] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const nameRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    nameRef.current?.focus();
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    const name = datasetName.trim();
    if (!name) {
      setError("评测集名称不能为空。");
      return;
    }
    const parsedRandomness = Number.parseFloat(randomness);
    if (!Number.isFinite(parsedRandomness) || parsedRandomness < 0 || parsedRandomness > 2) {
      setError("随机度需在 0 到 2 之间。");
      return;
    }
    const parsedSeed = seed.trim() === "" ? null : Number.parseInt(seed, 10);
    if (seed.trim() !== "" && !Number.isFinite(parsedSeed)) {
      setError("随机种子必须是整数。");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const job = await client.generateCandidates(projectId, documentId, {
        document_version_id: documentVersionId,
        dataset_name: name,
        capability_version: "candidate-generation-v1",
        prompt_version: promptVersion.trim() || "v1",
        seed: parsedSeed,
        randomness: parsedRandomness,
      });
      onGenerated(`已加入生成队列：评测集「${name}」，任务 ${job.job_id}。请到「评测集 / 审核队列」查看进度。`);
      onClose();
    } catch (reason: unknown) {
      setError(reason instanceof Error ? reason.message : "候选生成请求失败");
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4" onClick={onClose}>
      <div
        role="dialog"
        aria-modal="true"
        aria-label="生成候选评测集"
        className="w-full max-w-md rounded-lg border border-border bg-surface p-6 shadow-xl"
        onClick={(event) => event.stopPropagation()}
      >
        <h2 className="text-lg font-semibold text-text">生成候选评测集</h2>
        <p className="mt-1 text-sm text-muted">
          基于文档「{documentName}」的最新解析版本，调用候选生成 Provider 自动造题。生成结果需逐条人工审核后才可发布。
        </p>
        <form className="mt-5 space-y-4" onSubmit={(event) => void submit(event)}>
          <label className="block text-sm text-text">
            <span className="mb-1 block">评测集名称</span>
            <input
              ref={nameRef}
              className="w-full rounded-md border border-border bg-canvas px-3 py-2 text-text"
              value={datasetName}
              onChange={(event) => setDatasetName(event.target.value)}
              maxLength={255}
              aria-label="评测集名称"
              disabled={busy}
            />
          </label>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-sm text-text">
              <span className="mb-1 block">提示词版本</span>
              <input
                className="w-full rounded-md border border-border bg-canvas px-3 py-2 text-text"
                value={promptVersion}
                onChange={(event) => setPromptVersion(event.target.value)}
                maxLength={100}
                aria-label="提示词版本"
                disabled={busy}
              />
            </label>
            <label className="block text-sm text-text">
              <span className="mb-1 block">随机度 (0–2)</span>
              <input
                className="w-full rounded-md border border-border bg-canvas px-3 py-2 text-text"
                value={randomness}
                onChange={(event) => setRandomness(event.target.value)}
                inputMode="decimal"
                aria-label="随机度"
                disabled={busy}
              />
            </label>
          </div>
          <label className="block text-sm text-text">
            <span className="mb-1 block">随机种子（可选，留空则不固定）</span>
            <input
              className="w-full rounded-md border border-border bg-canvas px-3 py-2 text-text"
              value={seed}
              onChange={(event) => setSeed(event.target.value)}
              inputMode="numeric"
              placeholder="例如 42"
              aria-label="随机种子"
              disabled={busy}
            />
          </label>
          {error && (
            <p className="text-sm text-danger-foreground" role="alert">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-2 border-t border-border pt-4">
            <button
              type="button"
              className="rounded-md border border-border px-4 py-2 text-sm text-text disabled:opacity-50"
              onClick={onClose}
              disabled={busy}
            >
              取消
            </button>
            <button
              type="submit"
              className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90 disabled:opacity-50"
              disabled={busy}
            >
              {busy ? "提交中…" : "开始生成"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
