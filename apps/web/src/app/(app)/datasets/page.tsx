import { EmptyState } from "@/components/ui/empty-state";

export default function DatasetsPage() {
  return <EmptyState title="评测集" description="评测集未来负责组织可版本化的样例、标准答案与证据关系。当前仅提供页面入口。" actionLabel="前往文档库" actionHref="/documents" />;
}
