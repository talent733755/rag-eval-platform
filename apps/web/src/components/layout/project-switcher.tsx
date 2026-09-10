"use client";

import { useEffect, useState } from "react";

import { getProjectIdFromSearch, updateProjectQuery } from "../../lib/project-context";

type Project = {
  id: string;
  name: string;
};

type ProjectState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "invalid-selection"; requestedId: string; projects: Project[] }
  | { status: "ready"; projects: Project[]; selectedId: string };

const DEFAULT_API_BASE_URL = "http://localhost:8000";

export function ProjectSwitcher() {
  const [state, setState] = useState<ProjectState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    const queryProjectId = getProjectIdFromSearch(window.location.search);
    const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;
    const endpoint = `${baseUrl.replace(/\/$/, "")}/api/projects`;

    void fetch(endpoint, { signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`Project request failed with status ${response.status}`);
        }

        const payload: unknown = await response.json();
        return parseProjects(payload);
      })
      .then((projects) => {
        if (cancelled || controller.signal.aborted) {
          return;
        }

        if (queryProjectId) {
          if (!projects.some((project) => project.id === queryProjectId)) {
            setState({ status: "invalid-selection", requestedId: queryProjectId, projects });
            return;
          }

          setState({ status: "ready", projects, selectedId: queryProjectId });
          return;
        }

        if (projects.length === 0) {
          setState({ status: "empty" });
          return;
        }

        const selectedId = projects[0].id;
        updateProjectQuery(selectedId);
        setState({ status: "ready", projects, selectedId });
      })
      .catch((error: unknown) => {
        if (cancelled || controller.signal.aborted || isAbortError(error)) {
          return;
        }

        setState({ status: "error", message: "项目加载失败，请检查 API 服务后重试。" });
      });

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, []);

  if (state.status === "loading") {
    return <p aria-live="polite" role="status" className="px-5 py-4 text-xs text-slate-400">正在加载项目</p>;
  }

  if (state.status === "error") {
    return <p role="alert" className="px-5 py-4 text-xs text-amber-200">{state.message}</p>;
  }

  if (state.status === "empty") {
    return <p aria-live="polite" role="status" className="px-5 py-4 text-xs text-slate-400">暂无可用项目</p>;
  }

  if (state.status === "invalid-selection") {
    return (
      <p aria-live="polite" role="status" className="px-5 py-4 text-xs text-amber-200">
        当前项目不可用（未在可见项目中找到）
      </p>
    );
  }

  return (
    <label className="min-w-48 text-xs text-muted">
      <span className="sr-only">当前项目</span>
      <select
        aria-label="当前项目"
        className="block w-full rounded-md border border-border bg-surface px-2 py-2 font-medium text-text outline-none focus-visible:ring-2 focus-visible:ring-primary"
        value={state.selectedId}
        onChange={(event) => {
          const selectedId = event.target.value;
          if (!state.projects.some((project) => project.id === selectedId)) {
            return;
          }

          updateProjectQuery(selectedId);
          setState({ ...state, selectedId });
        }}
      >
        {state.projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function parseProjects(payload: unknown): Project[] {
  if (!Array.isArray(payload)) {
    throw new Error("Project response must be an array");
  }

  return payload.map((item, index): Project => {
    const record = typeof item === "object" && item !== null ? (item as Record<string, unknown>) : null;
    if (
      record === null ||
      typeof record.id !== "string" ||
      typeof record.name !== "string" ||
      record.id.length === 0 ||
      record.name.length === 0
    ) {
      throw new Error(`Project response entry ${index} is malformed`);
    }

    return { id: record.id, name: record.name };
  });
}

function isAbortError(error: unknown): boolean {
  return (
    typeof error === "object" &&
    error !== null &&
    "name" in error &&
    error.name === "AbortError"
  );
}
