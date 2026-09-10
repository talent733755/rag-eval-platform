import { EmptyState } from "@/components/ui/empty-state";

export default function RunsPage() {
  return <EmptyState title="运行记录" description="运行记录未来负责展示评测任务的状态、环境、配置和结果链接，支持复现与审计。" actionLabel="前往实验任务" actionHref="/experiments" />;
}
