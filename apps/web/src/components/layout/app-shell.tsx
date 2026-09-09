"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import type { KeyboardEvent } from "react";

const navigation = [
  { label: "工作台", href: "/", active: true },
  {
    label: "数据资产",
    items: ["文档库", "评测集", "审核队列"],
  },
  {
    label: "评测实验",
    items: ["Pipeline 接入", "实验任务", "运行记录"],
  },
  {
    label: "分析诊断",
    items: ["指标看板", "Trace 分析", "失败案例"],
  },
  {
    label: "系统管理",
    items: ["模型与服务", "项目与成员"],
  },
] as const;

function SidebarContent({ onNavigate, showBrand = true }: { onNavigate?: () => void; showBrand?: boolean }) {
  return (
    <div className="flex h-full flex-col">
      {showBrand && (
        <div className="flex h-16 shrink-0 items-center border-b border-white/10 px-5">
          <Link
            className="rounded-md text-sm font-semibold tracking-wide text-white focus-visible:outline-white"
            href="/"
            onClick={onNavigate}
          >
            RAG Eval Platform
          </Link>
        </div>
      )}
      <nav aria-label="主导航" className="flex-1 overflow-y-auto px-3 py-5">
        <ul className="space-y-5">
          {navigation.map((section) => (
            <li key={section.label}>
              {"items" in section ? (
                <>
                  <p className="px-3 text-xs font-semibold uppercase tracking-wider text-slate-400">
                    {section.label}
                  </p>
                  <ul className="mt-2 space-y-1">
                    {section.items.map((item) => (
                      <li key={item}>
                        <a
                          className="block rounded-md px-3 py-2 text-sm text-slate-300 transition-colors hover:bg-white/10 hover:text-white focus-visible:outline-white"
                          href="#"
                          onClick={onNavigate}
                        >
                          {item}
                        </a>
                      </li>
                    ))}
                  </ul>
                </>
              ) : (
                <a
                  aria-current="page"
                  className="block rounded-md border-l-2 border-primary bg-white/10 px-3 py-2 text-sm font-medium text-white transition-colors hover:bg-white/15 focus-visible:outline-white"
                  href={section.href}
                  onClick={onNavigate}
                >
                  {section.label}
                </a>
              )}
            </li>
          ))}
        </ul>
      </nav>
      <div className="border-t border-white/10 px-5 py-4 text-xs text-slate-400">
        <p>当前项目</p>
        <p className="mt-1 truncate font-medium text-slate-200">示例评测项目</p>
      </div>
    </div>
  );
}

export function AppShell({ children }: Readonly<{ children: ReactNode }>) {
  const [drawerOpen, setDrawerOpen] = useState(false);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const wasDrawerOpenRef = useRef(false);

  useEffect(() => {
    if (drawerOpen) {
      closeRef.current?.focus();
      wasDrawerOpenRef.current = true;
    } else if (wasDrawerOpenRef.current) {
      triggerRef.current?.focus();
      wasDrawerOpenRef.current = false;
    }
  }, [drawerOpen]);

  const closeDrawer = () => setDrawerOpen(false);

  const handleDrawerKeyDown = (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      closeDrawer();
      return;
    }

    if (event.key !== "Tab") {
      return;
    }

    const focusable = Array.from(
      event.currentTarget.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    );

    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }

    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    const activeElement = event.currentTarget.ownerDocument.activeElement;

    if (event.shiftKey && activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className="min-h-screen bg-canvas text-text">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-sidebar bg-sidebar md:block" aria-label="桌面侧边导航">
        <SidebarContent />
      </aside>

      {drawerOpen && (
        <div className="fixed inset-0 z-40 md:hidden" role="presentation">
          <button
            aria-label="关闭导航背景"
            className="absolute inset-0 h-full w-full cursor-default bg-slate-950/50"
            onClick={closeDrawer}
            tabIndex={-1}
            type="button"
          />
          <aside
            aria-labelledby="mobile-navigation-title"
            aria-modal="true"
            className="relative flex h-full w-[min(18rem,calc(100%-2rem))] flex-col bg-sidebar shadow-xl"
            id="mobile-navigation"
            onKeyDown={handleDrawerKeyDown}
            role="dialog"
          >
            <div className="flex h-16 shrink-0 items-center justify-between border-b border-white/10 px-5">
              <h2 className="text-sm font-semibold tracking-wide text-white" id="mobile-navigation-title">
                导航菜单
              </h2>
              <button
                aria-label="关闭导航菜单"
                className="inline-flex h-9 w-9 items-center justify-center rounded-md text-slate-300 hover:bg-white/10 hover:text-white focus-visible:outline-white"
                onClick={closeDrawer}
                ref={closeRef}
                type="button"
              >
                <svg aria-hidden="true" className="h-5 w-5" fill="none" viewBox="0 0 24 24">
                  <path d="m6 6 12 12M18 6 6 18" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
                </svg>
              </button>
            </div>
            <div className="min-h-0 flex-1">
              <SidebarContent onNavigate={closeDrawer} showBrand={false} />
            </div>
          </aside>
        </div>
      )}

      <div className="md:pl-sidebar">
        <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-border bg-surface/95 px-4 backdrop-blur sm:px-6 lg:px-8">
          <div className="flex min-w-0 items-center gap-3">
            <button
              aria-controls="mobile-navigation"
              aria-expanded={drawerOpen}
              aria-label="打开导航菜单"
              className="inline-flex h-9 w-9 items-center justify-center rounded-md border border-border text-text-secondary hover:bg-canvas md:hidden"
              onClick={() => setDrawerOpen(true)}
              ref={triggerRef}
              type="button"
            >
              <svg aria-hidden="true" className="h-5 w-5" fill="none" viewBox="0 0 24 24">
                <path d="M4 6h16M4 12h16M4 18h16" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
              </svg>
            </button>
            <div className="hidden min-w-0 items-center gap-2 text-sm sm:flex">
              <span className="font-medium text-text">示例组织</span>
              <span aria-hidden="true" className="text-muted">/</span>
              <span className="truncate text-muted">示例评测项目</span>
            </div>
          </div>
          <div className="flex items-center gap-2 sm:gap-3">
            <button
              aria-label="搜索"
              className="hidden rounded-md px-3 py-2 text-sm text-muted hover:bg-canvas hover:text-text sm:inline-flex"
              type="button"
            >
              搜索
            </button>
            <button
              aria-label="查看通知"
              className="rounded-md px-3 py-2 text-sm text-muted hover:bg-canvas hover:text-text"
              type="button"
            >
              通知
            </button>
            <button
              aria-label="打开用户菜单"
              className="rounded-md border border-border px-3 py-2 text-sm font-medium text-text hover:bg-canvas"
              type="button"
            >
              用户
            </button>
          </div>
        </header>
        <main className="px-4 py-6 sm:px-6 sm:py-8 lg:px-8">{children}</main>
      </div>
    </div>
  );
}
