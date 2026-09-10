import { useSyncExternalStore } from "react";

const PROJECT_CONTEXT_EVENT = "project-context-change";

export function getProjectIdFromSearch(search: string): string | null {
  return new URLSearchParams(search).get("project");
}

export function preserveProjectQuery(href: string, search: string): string {
  const projectId = getProjectIdFromSearch(search);
  if (!projectId) {
    return href;
  }

  const url = new URL(href, "http://rag-eval-platform.local");
  url.searchParams.set("project", projectId);
  return `${url.pathname}${url.search}${url.hash}`;
}

export function updateProjectQuery(projectId: string): void {
  const url = new URL(window.location.href);
  url.searchParams.set("project", projectId);
  window.history.replaceState(window.history.state, "", url);
  window.dispatchEvent(new Event(PROJECT_CONTEXT_EVENT));
}

export function useProjectSearch(): string {
  return useSyncExternalStore(subscribeToProjectContext, getBrowserSearch, getServerSearch);
}

function subscribeToProjectContext(onStoreChange: () => void): () => void {
  window.addEventListener("popstate", onStoreChange);
  window.addEventListener(PROJECT_CONTEXT_EVENT, onStoreChange);

  return () => {
    window.removeEventListener("popstate", onStoreChange);
    window.removeEventListener(PROJECT_CONTEXT_EVENT, onStoreChange);
  };
}

function getBrowserSearch(): string {
  return window.location.search;
}

function getServerSearch(): string {
  return "";
}
