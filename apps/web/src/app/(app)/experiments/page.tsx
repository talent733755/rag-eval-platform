import { EmptyState } from "@/components/ui/empty-state";

export default function ExperimentsPage() {
  return <EmptyState title="实验任务" description="实验任务未来负责选择评测集、Pipeline 和运行配置，创建可复现的评测任务。" actionLabel="配置 Pipeline 接入" actionHref="/adapters" />;
}
