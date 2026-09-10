import { EmptyState } from "@/components/ui/empty-state";

export default function TracesPage() {
  return <EmptyState title="Trace 分析" description="Trace 分析未来负责查看从查询改写到最终回答的完整链路，并定位各阶段行为。" actionLabel="查看失败案例" actionHref="/failures" />;
}
