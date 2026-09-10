import { EmptyState } from "@/components/ui/empty-state";

export default function ServicesPage() {
  return <EmptyState title="模型与服务" description="模型与服务未来负责管理模型、Embedding、Reranker 和相关服务配置，供 Adapter 使用。" actionLabel="返回工作台" actionHref="/" />;
}
