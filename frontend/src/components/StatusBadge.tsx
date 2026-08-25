import { Badge } from "@/components/ui/badge";
import type { ModuleStatus, ReconTaskStatus, TargetStatus } from "@/lib/api";

const map: Record<ReconTaskStatus | TargetStatus | ModuleStatus, { variant: any; label: string }> = {
  queued: { variant: "info", label: "Queued" },
  pending: { variant: "outline", label: "Pending" },
  running: { variant: "warning", label: "Running" },
  completed: { variant: "success", label: "Completed" },
  failed: { variant: "destructive", label: "Failed" },
  cancelled: { variant: "secondary", label: "Cancelled" },
  skipped: { variant: "secondary", label: "Skipped" },
  retry_wait: { variant: "warning", label: "Retry wait" },
  blocked: { variant: "outline", label: "Blocked" },
};

export function StatusBadge({ status }: { status: TargetStatus | ModuleStatus | ReconTaskStatus }) {
  const m = map[status] ?? { variant: "outline", label: status };
  return <Badge variant={m.variant}>{m.label}</Badge>;
}
