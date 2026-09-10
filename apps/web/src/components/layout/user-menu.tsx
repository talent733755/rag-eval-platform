"use client";

import { useState } from "react";

type UserMenuProps = {
  actorLabel?: string;
};

export function UserMenu({ actorLabel = "开发用户" }: UserMenuProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="relative">
      <button
        aria-expanded={open}
        aria-haspopup="menu"
        className="rounded-md border border-border px-3 py-2 text-sm font-medium text-text hover:bg-canvas"
        onClick={() => setOpen((current) => !current)}
        type="button"
      >
        {actorLabel}
      </button>
      {open && (
        <div aria-label="用户菜单" className="absolute right-0 top-full z-30 mt-2 min-w-36 rounded-md border border-border bg-surface p-1 shadow-lg" role="menu">
          <span className="block px-3 py-2 text-xs text-muted" role="menuitem">当前为开发角色</span>
        </div>
      )}
    </div>
  );
}
