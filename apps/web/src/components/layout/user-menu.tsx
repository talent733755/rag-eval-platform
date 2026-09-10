"use client";

import { useEffect, useState } from "react";

type UserMenuProps = {
  actorLabel?: string;
};

export function UserMenu({ actorLabel = "开发用户" }: UserMenuProps) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    if (!open) {
      return;
    }

    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
      }
    };

    document.addEventListener("keydown", closeOnEscape);
    return () => document.removeEventListener("keydown", closeOnEscape);
  }, [open]);

  return (
    <div className="relative">
      <button
        aria-controls="user-menu-popover"
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label="打开用户菜单"
        className="rounded-md border border-border px-3 py-2 text-sm font-medium text-text hover:bg-canvas"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        {actorLabel}
      </button>
      {open && (
        <div aria-label="用户菜单" className="absolute right-0 top-full z-30 mt-2 min-w-36 rounded-md border border-border bg-surface p-1 shadow-lg" id="user-menu-popover" role="dialog">
          <p className="block px-3 py-2 text-xs text-muted">当前为开发角色</p>
        </div>
      )}
    </div>
  );
}
