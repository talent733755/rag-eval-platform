"use client";

import { hasPermission, type UserRole } from "../../lib/auth/permissions";
import { isNavigationGroup, isNavigationItemActive, navigation } from "../../lib/navigation";
import { ProjectLink } from "../ui/project-link";

type SidebarNavProps = {
  role: UserRole;
  pathname: string;
  onNavigate?: () => void;
};

export function SidebarNav({ onNavigate, pathname, role }: SidebarNavProps) {
  return (
    <nav aria-label="主导航" className="flex-1 overflow-y-auto px-3 py-5">
      <ul className="space-y-5">
        {navigation.map((entry) => {
          if (!isNavigationGroup(entry)) {
            if (!hasPermission(role, entry.permission)) {
              return null;
            }

            return (
              <li key={entry.href}>
                <NavigationLink item={entry} pathname={pathname} onNavigate={onNavigate} />
              </li>
            );
          }

          const visibleChildren = entry.children.filter((item) => hasPermission(role, item.permission));
          if (visibleChildren.length === 0) {
            return null;
          }

          return (
            <li key={entry.label}>
              <p className="px-3 text-xs font-semibold uppercase tracking-wider text-slate-400">{entry.label}</p>
              <ul className="mt-2 space-y-1">
                {visibleChildren.map((item) => (
                  <li key={item.href}>
                    <NavigationLink item={item} pathname={pathname} onNavigate={onNavigate} />
                  </li>
                ))}
              </ul>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function NavigationLink({
  item,
  onNavigate,
  pathname,
}: {
  item: { label: string; href: string };
  onNavigate?: () => void;
  pathname: string;
}) {
  const active = isNavigationItemActive(pathname, item.href);

  return (
    <ProjectLink
      aria-current={active ? "page" : undefined}
      className={[
        "block rounded-md px-3 py-2 text-sm transition-colors focus-visible:outline-white",
        active
          ? "border-l-2 border-primary bg-white/10 font-medium text-white"
          : "text-slate-300 hover:bg-white/10 hover:text-white",
      ].join(" ")}
      href={item.href}
      onClick={onNavigate}
    >
      {item.label}
    </ProjectLink>
  );
}
