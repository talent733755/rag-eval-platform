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
  up: "text-success-foreground",
  down: "text-danger-foreground",
  neutral: "text-muted",
};

const trendLabels: Record<TrendDirection, string> = {
  up: "趋势上升",
  down: "趋势下降",
  neutral: "趋势持平",
};

const trendPaths: Record<TrendDirection, string> = {
  up: "m5 15 5-5 3 3 6-7M14 6h5v5",
  down: "m5 9 5 5 3-3 6 7M14 18h5v-5",
  neutral: "M4 12h16",
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
            <span
              className={`inline-flex items-center font-medium ${trendStyles[trend.direction ?? "neutral"]}`}
              data-testid={`data-card-trend-${trend.direction ?? "neutral"}`}
            >
              <svg
                aria-hidden="true"
                className="mr-1 h-3.5 w-3.5 shrink-0"
                data-trend-marker
                fill="none"
                viewBox="0 0 24 24"
              >
                <path d={trendPaths[trend.direction ?? "neutral"]} stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" />
              </svg>
              <span className="sr-only">{trendLabels[trend.direction ?? "neutral"]}</span>
              {trend.value}
              {trend.label && <span className="ml-1 font-normal text-muted">{trend.label}</span>}
            </span>
          )}
        </div>
      )}
    </article>
  );
}
