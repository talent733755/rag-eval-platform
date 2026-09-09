import { DataCard } from "@/components/ui/data-card";
import { StatusBadge } from "@/components/ui/status-badge";

export default function DashboardPage() {
  return (
    <div className="mx-auto max-w-screen-2xl space-y-6">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-end sm:justify-between">
        <div>
          <p className="text-sm font-medium text-primary">工作台</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-text sm:text-3xl">
            评测工作台
          </h1>
          <p className="mt-2 max-w-2xl text-sm text-muted">
            这里是管理后台基础壳层示例，业务模块将在后续迭代中接入。
          </p>
        </div>
        <StatusBadge status="info">基础壳层可用</StatusBadge>
      </div>

      <section aria-labelledby="overview-heading">
        <h2 id="overview-heading" className="sr-only">
          概览
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <DataCard label="证据命中率" value="—" supportingText="等待评测数据" />
          <DataCard label="Faithfulness" value="—" supportingText="等待评测数据" />
          <DataCard label="本周实验" value="0" supportingText="尚未创建实验" />
          <DataCard label="待审核样例" value="0" supportingText="队列为空" />
        </div>
      </section>

      <section className="rounded-lg border border-dashed border-border bg-surface p-6" aria-labelledby="next-heading">
        <h2 id="next-heading" className="text-base font-semibold text-text">
          下一步
        </h2>
        <p className="mt-2 max-w-2xl text-sm text-muted">
          先配置项目和数据资产，再运行一次评测以查看质量趋势、失败样例和 Trace 诊断。
        </p>
      </section>
    </div>
  );
}
