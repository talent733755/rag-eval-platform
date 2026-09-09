import type { HTMLAttributes, ReactNode } from "react";

export const statusBadgeStatuses = [
  "success",
  "warning",
  "danger",
  "info",
  "neutral",
  "failed",
] as const;

export type StatusBadgeStatus = (typeof statusBadgeStatuses)[number];

type StatusBadgeProps = Omit<HTMLAttributes<HTMLSpanElement>, "children"> & {
  children: ReactNode;
  status: StatusBadgeStatus;
};

const statusStyles: Record<StatusBadgeStatus, string> = {
  success: "border-success/30 bg-success/10 text-success",
  warning: "border-warning/30 bg-warning/10 text-warning",
  danger: "border-danger/30 bg-danger/10 text-danger",
  failed: "border-danger/30 bg-danger/10 text-danger",
  info: "border-primary/30 bg-primary-soft text-primary",
  neutral: "border-border bg-canvas text-muted",
};

export function StatusBadge({ children, className, status, ...props }: StatusBadgeProps) {
  const classes = [
    "inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium leading-none",
    statusStyles[status],
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <span {...props} className={classes} data-status={status} role="status">
      <span aria-hidden="true" className="h-1.5 w-1.5 shrink-0 rounded-full bg-current" />
      <span>{children}</span>
    </span>
  );
}
