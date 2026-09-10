import { EmptyState } from "@/components/ui/empty-state";

export default function MetricsPage() {
  return <EmptyState title="指标看板" description="指标看板未来负责汇总检索、生成、延迟和成本指标，支持按实验与版本比较。" actionLabel="查看运行记录" actionHref="/runs" />;
}
