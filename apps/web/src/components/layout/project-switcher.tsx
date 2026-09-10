"use client";

import { useEffect, useState } from "react";

import {
  getProjectIdFromSearch,
  updateProjectQuery,
  useProjectSearch,
} from "../../lib/project-context";

type Project = {
  id: string;
  name: string;
};

type ProjectState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "empty" }
  | { status: "invalid-selection"; requestedId: string; projects: Project[] }
  | { status: "ready"; projects: Project[]; selectedId: string | null };

type ProjectSwitcherProps = {
  requestTimeoutMs?: number;
  maxAttempts?: number;
  retryDelayMs?: number;
};

type RequestOptions = {
  requestTimeoutMs: number;
  maxAttempts: number;
  retryDelayMs: number;
};

type SharedRequest = {
  controller: AbortController;
  promise: Promise<Project[]>;
  subscribers: number;
  settled: boolean;
  abortTimer?: ReturnType<typeof setTimeout>;
};

const DEFAULT_API_BASE_URL = "http://localhost:8000";
const DEFAULT_REQUEST_TIMEOUT_MS = 5_000;
const DEFAULT_MAX_ATTEMPTS = 3;
const DEFAULT_RETRY_DELAY_MS = 100;
const pendingRequests = new Map<string, SharedRequest>();

export function ProjectSwitcher({
  maxAttempts = DEFAULT_MAX_ATTEMPTS,
  requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  retryDelayMs = DEFAULT_RETRY_DELAY_MS,
}: ProjectSwitcherProps) {
  const projectSearch = useProjectSearch();
  const endpoint = getProjectsEndpoint();
  const [retryNonce, setRetryNonce] = useState(0);
  const [state, setState] = useState<ProjectState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const request = acquireProjectRequest(endpoint, {
      maxAttempts,
      requestTimeoutMs,
      retryDelayMs,
    });

    setState({ status: "loading" });
    void request.promise
      .then((projects) => {
        if (cancelled) {
          return;
        }

        const queryProjectId = getProjectIdFromSearch(window.location.search);
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
        if (cancelled || isAbortError(error)) {
          return;
        }

        setState({ status: "error", message: "项目加载失败，请检查 API 服务后重试。" });
      });

    return () => {
      cancelled = true;
      request.release();
    };
  }, [endpoint, maxAttempts, requestTimeoutMs, retryDelayMs, retryNonce]);

  useEffect(() => {
    if (state.status !== "ready" && state.status !== "invalid-selection") {
      return;
    }

    const queryProjectId = getProjectIdFromSearch(projectSearch);
    const projects = state.projects;

    if (queryProjectId && projects.some((project) => project.id === queryProjectId)) {
      if (state.status !== "ready" || state.selectedId !== queryProjectId) {
        setState({ status: "ready", projects, selectedId: queryProjectId });
      }
      return;
    }

    if (queryProjectId) {
      if (state.status !== "invalid-selection" || state.requestedId !== queryProjectId) {
        setState({ status: "invalid-selection", requestedId: queryProjectId, projects });
      }
      return;
    }

    if (state.status !== "ready" || state.selectedId !== null) {
      setState({ status: "ready", projects, selectedId: null });
    }
  }, [projectSearch, state]);

  if (state.status === "loading") {
    return <p aria-live="polite" role="status" className="px-5 py-4 text-xs text-slate-400">正在加载项目</p>;
  }

  if (state.status === "error") {
    return (
      <div role="alert" className="flex items-center gap-2 px-5 py-4 text-xs text-amber-200">
        <span>{state.message}</span>
        <button
          className="rounded border border-amber-200/50 px-2 py-1 font-medium hover:bg-white/10"
          onClick={() => {
            setState({ status: "loading" });
            setRetryNonce((current) => current + 1);
          }}
          type="button"
        >
          重试项目加载
        </button>
      </div>
    );
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
        value={state.selectedId ?? ""}
        onChange={(event) => {
          const selectedId = event.target.value;
          if (!state.projects.some((project) => project.id === selectedId)) {
            return;
          }

          updateProjectQuery(selectedId);
          setState({ ...state, selectedId });
        }}
      >
        <option disabled value="">
          未选择项目
        </option>
        {state.projects.map((project) => (
          <option key={project.id} value={project.id}>
            {project.name}
          </option>
        ))}
      </select>
    </label>
  );
}

function getProjectsEndpoint(): string {
  const baseUrl = process.env.NEXT_PUBLIC_API_BASE_URL ?? DEFAULT_API_BASE_URL;
  return `${baseUrl.replace(/\/$/, "")}/api/projects`;
}

function acquireProjectRequest(endpoint: string, options: RequestOptions): {
  promise: Promise<Project[]>;
  release: () => void;
} {
  const key = `${endpoint}:${options.requestTimeoutMs}:${options.maxAttempts}:${options.retryDelayMs}`;
  let shared = pendingRequests.get(key);

  if (!shared) {
    const controller = new AbortController();
    const promise = loadProjects(endpoint, controller.signal, options);
    shared = { controller, promise, settled: false, subscribers: 0 };
    pendingRequests.set(key, shared);

    void promise.then(
      () => settleSharedRequest(key, shared as SharedRequest),
      () => settleSharedRequest(key, shared as SharedRequest),
    );
  }

  if (shared.abortTimer) {
    clearTimeout(shared.abortTimer);
    shared.abortTimer = undefined;
  }
  shared.subscribers += 1;

  let released = false;
  return {
    promise: shared.promise,
    release: () => {
      if (released) {
        return;
      }
      released = true;
      shared!.subscribers -= 1;

      if (shared!.subscribers === 0 && !shared!.settled) {
        shared!.abortTimer = setTimeout(() => {
          if (shared!.subscribers === 0 && !shared!.settled) {
            shared!.controller.abort();
            pendingRequests.delete(key);
          }
        }, 0);
      }
    },
  };
}

function settleSharedRequest(key: string, shared: SharedRequest): void {
  shared.settled = true;
  if (pendingRequests.get(key) === shared) {
    pendingRequests.delete(key);
  }
}

async function loadProjects(
  endpoint: string,
  signal: AbortSignal,
  options: RequestOptions,
): Promise<Project[]> {
  for (let attempt = 1; attempt <= options.maxAttempts; attempt += 1) {
    if (signal.aborted) {
      throw createAbortError();
    }

    try {
      return await requestProjectsOnce(endpoint, signal, options.requestTimeoutMs);
    } catch (error: unknown) {
      if (signal.aborted || isAbortError(error) || isMalformedProjectError(error)) {
        throw error;
      }
      if (attempt === options.maxAttempts) {
        throw error;
      }
      await waitBeforeRetry(options.retryDelayMs, signal);
    }
  }

  throw new Error("Project request exhausted retries");
}

async function requestProjectsOnce(endpoint: string, parentSignal: AbortSignal, timeoutMs: number): Promise<Project[]> {
  const attemptController = new AbortController();
  let timedOut = false;
  const onParentAbort = () => attemptController.abort();
  const timeoutId = setTimeout(() => {
    timedOut = true;
    attemptController.abort();
  }, timeoutMs);
  parentSignal.addEventListener("abort", onParentAbort, { once: true });

  const operation = fetch(endpoint, { signal: attemptController.signal }).then(async (response) => {
    if (!response.ok) {
      throw new Error(`Project request failed with status ${response.status}`);
    }
    return parseProjects(await response.json());
  });
  const abort = new Promise<never>((_resolve, reject) => {
    if (attemptController.signal.aborted) {
      reject(createAbortError());
      return;
    }
    attemptController.signal.addEventListener("abort", () => reject(createAbortError()), { once: true });
  });

  try {
    return await Promise.race([operation, abort]);
  } catch (error: unknown) {
    if (timedOut) {
      throw new Error("Project request timed out");
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    parentSignal.removeEventListener("abort", onParentAbort);
  }
}

function waitBeforeRetry(delayMs: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) {
    return Promise.reject(createAbortError());
  }
  if (delayMs <= 0) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    const timer = setTimeout(resolve, delayMs);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(createAbortError());
      },
      { once: true },
    );
  });
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
      const error = new Error(`Project response entry ${index} is malformed`);
      error.name = "MalformedProjectResponseError";
      throw error;
    }

    return { id: record.id, name: record.name };
  });
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
}

function isMalformedProjectError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "MalformedProjectResponseError";
}

function createAbortError(): Error {
  const error = new Error("The operation was aborted");
  error.name = "AbortError";
  return error;
}
