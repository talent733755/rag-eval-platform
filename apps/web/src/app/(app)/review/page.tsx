import { EmptyState } from "@/components/ui/empty-state";

export default function ReviewPage() {
  return <EmptyState title="审核队列" description="审核队列未来负责人工校验自动生成的评测候选，并记录审核决策和审计信息。" actionLabel="前往评测集" actionHref="/datasets" />;
}
