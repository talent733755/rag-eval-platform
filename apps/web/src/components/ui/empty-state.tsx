import { ProjectLink } from "./project-link";

type EmptyStateProps = {
  title: string;
  description: string;
  actionLabel: string;
  actionHref: string;
};

export function EmptyState({ actionHref, actionLabel, description, title }: EmptyStateProps) {
  return (
    <section aria-labelledby="empty-state-title" className="mx-auto max-w-3xl rounded-lg border border-dashed border-border bg-surface p-8">
      <p className="text-sm font-medium text-primary">基础壳层</p>
      <h1 className="mt-2 text-2xl font-semibold tracking-tight text-text" id="empty-state-title">
        {title}
      </h1>
      <p className="mt-3 max-w-2xl text-sm leading-6 text-muted">{description}</p>
      <ProjectLink className="mt-6 inline-flex rounded-md bg-primary px-4 py-2 text-sm font-medium text-white hover:opacity-90" href={actionHref}>
        {actionLabel}
      </ProjectLink>
    </section>
  );
}
