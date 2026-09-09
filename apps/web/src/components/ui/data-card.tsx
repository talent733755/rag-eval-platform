import type { HTMLAttributes, ReactNode } from "react";

type TrendDirection = "up" | "down" | "neutral";

export type DataCardTrend = {
  direction?: TrendDirection;
  label?: ReactNode;
  value: ReactNode;
};

export type DataCardProps = Omit<HTMLAttributes<HTMLElement>, "title"> & {
  label: ReactNode;
  value: ReactNode;
  supportingText?: ReactNode;
  trend?: DataCardTrend;
};

const trendStyles: Record<TrendDirection, string> = {
  up: "text-success",
  down: "text-danger",
  neutral: "text-muted",
};

export function DataCard({
  className,
  label,
  supportingText,
  trend,
  value,
  ...props
}: DataCardProps) {
  const classes = [
    "rounded-lg border border-border bg-surface p-4 shadow-sm shadow-slate-900/5",
    className,
  ]
    .filter(Boolean)
    .join(" ");

  return (
    <article {...props} className={classes}>
      <p className="text-sm font-medium text-muted">{label}</p>
      <p className="mt-2 text-2xl font-semibold tracking-tight text-text">{value}</p>
      {(supportingText || trend) && (
        <div className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted">
          {supportingText && <span>{supportingText}</span>}
          {trend && (
            <span className={`font-medium ${trendStyles[trend.direction ?? "neutral"]}`}>
              {trend.value}
              {trend.label && <span className="ml-1 font-normal text-muted">{trend.label}</span>}
            </span>
          )}
        </div>
      )}
    </article>
  );
}
