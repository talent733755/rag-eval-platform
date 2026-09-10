import { EmptyState } from "@/components/ui/empty-state";

export default function FailuresPage() {
  return <EmptyState title="失败案例" description="失败案例未来负责归类评测失败、关联 Trace 和证据，帮助工程师定位回归原因。" actionLabel="前往 Trace 分析" actionHref="/traces" />;
}
