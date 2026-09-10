"use client";

import { useEffect, useMemo, useState } from "react";

import { ApiError, createApiClient } from "../../lib/api/client";
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
const MAX_REQUEST_TIMEOUT_MS = 30_000;
const MAX_MAX_ATTEMPTS = 5;
const MAX_RETRY_DELAY_MS = 5_000;
const pendingRequests = new Map<string, SharedRequest>();

class ProjectResponseError extends Error {
  constructor() {
    super("Project response could not be decoded");
    this.name = "ProjectResponseError";
  }
}

class ProjectSchemaError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ProjectSchemaError";
  }
}

class MalformedProjectResponseError extends Error {
  constructor(index: number) {
    super(`Project response entry ${index} is malformed`);
    this.name = "MalformedProjectResponseError";
  }
}

class ProjectTimeoutError extends Error {
  constructor() {
    super("Project request timed out");
    this.name = "ProjectTimeoutError";
  }
}

export function ProjectSwitcher({
  maxAttempts = DEFAULT_MAX_ATTEMPTS,
  requestTimeoutMs = DEFAULT_REQUEST_TIMEOUT_MS,
  retryDelayMs = DEFAULT_RETRY_DELAY_MS,
}: ProjectSwitcherProps) {
  const projectSearch = useProjectSearch();
  const endpoint = getProjectsEndpoint();
  const requestOptions = useMemo(
    () => normalizeRequestOptions({ maxAttempts, requestTimeoutMs, retryDelayMs }),
    [maxAttempts, requestTimeoutMs, retryDelayMs],
  );
  const [retryNonce, setRetryNonce] = useState(0);
  const [state, setState] = useState<ProjectState>({ status: "loading" });

  useEffect(() => {
    let cancelled = false;
    const request = acquireProjectRequest(endpoint, requestOptions);

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

        setState({ status: "error", message: getProjectErrorMessage(error) });
      });

    return () => {
      cancelled = true;
      request.release();
    };
  }, [endpoint, requestOptions, retryNonce]);

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

  if (shared.abortTimer !== undefined) {
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
  if (shared.abortTimer !== undefined) {
    clearTimeout(shared.abortTimer);
    shared.abortTimer = undefined;
  }
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
      if (signal.aborted || !isRetryableProjectError(error)) {
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

  const apiBaseUrl = endpoint.slice(0, -"/api/projects".length);
  const operation = createApiClient({ baseUrl: apiBaseUrl, fetchImpl: fetch })
    .listProjects({ signal: attemptController.signal })
    .then((payload) => parseProjects(payload))
    .catch((error: unknown) => {
      if (error instanceof SyntaxError) {
        throw new ProjectResponseError();
      }
      throw error;
    });
  let onAttemptAbort: (() => void) | undefined;
  const abort = new Promise<never>((_resolve, reject) => {
    onAttemptAbort = () => reject(createAbortError());

    if (attemptController.signal.aborted) {
      reject(createAbortError());
      return;
    }
    attemptController.signal.addEventListener("abort", onAttemptAbort, { once: true });
  });

  try {
    return await Promise.race([operation, abort]);
  } catch (error: unknown) {
    if (timedOut) {
      throw new ProjectTimeoutError();
    }
    throw error;
  } finally {
    clearTimeout(timeoutId);
    parentSignal.removeEventListener("abort", onParentAbort);
    if (onAttemptAbort) {
      attemptController.signal.removeEventListener("abort", onAttemptAbort);
    }
  }
}

export function waitBeforeRetry(delayMs: number, signal: AbortSignal): Promise<void> {
  if (signal.aborted) {
    return Promise.reject(createAbortError());
  }
  if (delayMs <= 0) {
    return Promise.resolve();
  }

  return new Promise((resolve, reject) => {
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      resolve();
    }, delayMs);
    const onAbort = () => {
      if (settled) {
        return;
      }
      settled = true;
      cleanup();
      reject(createAbortError());
    };
    const cleanup = () => {
      clearTimeout(timer);
      signal.removeEventListener("abort", onAbort);
    };

    signal.addEventListener("abort", onAbort, { once: true });
  });
}

function parseProjects(payload: unknown): Project[] {
  if (!Array.isArray(payload)) {
    throw new ProjectSchemaError("Project response must be an array");
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
      throw new MalformedProjectResponseError(index);
    }

    return { id: record.id, name: record.name };
  });
}

function isAbortError(error: unknown): boolean {
  return typeof error === "object" && error !== null && "name" in error && error.name === "AbortError";
}

function isRetryableProjectError(error: unknown): boolean {
  if (
    isAbortError(error) ||
    error instanceof MalformedProjectResponseError ||
    error instanceof ProjectResponseError ||
    error instanceof ProjectSchemaError
  ) {
    return false;
  }
  if (error instanceof ApiError) {
    return error.status === 408 || error.status === 429 || (error.status >= 500 && error.status !== 501);
  }
  return error instanceof ProjectTimeoutError || error instanceof Error;
}

function createAbortError(): Error {
  const error = new Error("The operation was aborted");
  error.name = "AbortError";
  return error;
}

function getProjectErrorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    if (error.status === 408 || error.status === 429 || (error.status >= 500 && error.status !== 501)) {
      return `项目加载失败（HTTP ${error.status}），请稍后重试。`;
    }
    return `项目加载失败（HTTP ${error.status}），请检查权限或请求配置。`;
  }
  if (error instanceof ProjectTimeoutError) {
    return "项目加载超时，请检查 API 服务后重试。";
  }
  if (error instanceof ProjectSchemaError || error instanceof MalformedProjectResponseError) {
    return "项目响应格式无效，请检查 API 返回的数据结构。";
  }
  return "项目加载失败，请检查 API 服务后重试。";
}

function normalizeRequestOptions(options: RequestOptions): RequestOptions {
  return {
    maxAttempts: normalizeMaxAttempts(options.maxAttempts),
    requestTimeoutMs: normalizeNonNegativeOption(
      options.requestTimeoutMs,
      DEFAULT_REQUEST_TIMEOUT_MS,
      MAX_REQUEST_TIMEOUT_MS,
    ),
    retryDelayMs: normalizeNonNegativeOption(options.retryDelayMs, DEFAULT_RETRY_DELAY_MS, MAX_RETRY_DELAY_MS),
  };
}

function normalizeMaxAttempts(value: number): number {
  if (!Number.isFinite(value) || !Number.isInteger(value)) {
    return DEFAULT_MAX_ATTEMPTS;
  }
  return Math.min(Math.max(value, 1), MAX_MAX_ATTEMPTS);
}

function normalizeNonNegativeOption(value: number, fallback: number, maximum: number): number {
  if (!Number.isFinite(value) || value < 0) {
    return fallback;
  }
  return Math.min(value, maximum);
}
