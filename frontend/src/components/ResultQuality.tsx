import {
  AlertTriangle,
  CheckCircle2,
  Clock3,
  DatabaseZap,
  HeartPulse,
  ShieldAlert,
} from "lucide-react";
import type { ReactNode } from "react";

import type {
  ModuleHealth,
  ReconTask,
  ScanKnowledgeSummary,
  SourceYield,
  TaskList,
} from "@/lib/api";
import { formatRelative } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const DISCOVERY_BOUND_KEYS = [
  "pagination_truncated",
  "source_truncated",
  "body_truncated",
  "stdout_truncated",
  "stderr_truncated",
] as const;
const EVIDENCE_BOUND_KEYS = [
  "raw_output_truncated",
  "raw_output_scan_budget_exhausted",
] as const;

export interface QualitySignals {
  sampled: number;
  total: number;
  discoveryBoundTasks: number;
  evidenceBoundTasks: number;
  rejectedEmissions: number;
}

function hasTrueFlag(task: ReconTask, keys: readonly string[]) {
  return keys.some((key) => task.output_summary[key] === true);
}

export function inspectTaskQuality(tasks?: TaskList): QualitySignals {
  const items = tasks?.items ?? [];
  return {
    sampled: items.length,
    total: tasks?.total ?? 0,
    discoveryBoundTasks: items.filter((task) =>
      hasTrueFlag(task, DISCOVERY_BOUND_KEYS),
    ).length,
    evidenceBoundTasks: items.filter((task) =>
      hasTrueFlag(task, EVIDENCE_BOUND_KEYS),
    ).length,
    rejectedEmissions: items.reduce((total, task) => {
      const count = task.output_summary.validation_error_count;
      return total + (typeof count === "number" && Number.isFinite(count) ? count : 0);
    }, 0),
  };
}

function fallbackHealth(tasks?: TaskList): ModuleHealth[] {
  const byModule = new Map<string, ModuleHealth>();
  for (const task of tasks?.items ?? []) {
    const row = byModule.get(task.module_name) ?? {
      module_name: task.module_name,
      capability: task.capability,
      tasks_total: 0,
      tasks_by_status: {},
      failure_rate: 0,
    };
    row.tasks_total += 1;
    row.tasks_by_status[task.status] = (row.tasks_by_status[task.status] ?? 0) + 1;
    row.failure_rate = (row.tasks_by_status.failed ?? 0) / row.tasks_total;
    byModule.set(task.module_name, row);
  }
  return [...byModule.values()];
}

function fallbackSourceYield(summary?: ScanKnowledgeSummary): SourceYield[] {
  return Object.entries(summary?.observations_by_module ?? {}).map(
    ([source_module, observations]) => ({
      source_module,
      source_name: null,
      observations,
      distinct_assets: 0,
      exclusive_assets: 0,
      average_confidence: 0,
      last_observed_at: null,
    }),
  );
}

function statusCount(row: ModuleHealth, status: string) {
  return row.tasks_by_status[status] ?? 0;
}

function moduleState(row: ModuleHealth) {
  const failed = statusCount(row, "failed");
  const completed = statusCount(row, "completed");
  if (failed > 0 && completed === 0) {
    return { label: "failing", className: "border-rose-500/30 text-rose-600 dark:text-rose-400" };
  }
  if (failed > 0 || statusCount(row, "blocked") > 0) {
    return { label: "degraded", className: "border-amber-500/30 text-amber-700 dark:text-amber-300" };
  }
  if (statusCount(row, "running") > 0 || statusCount(row, "retry_wait") > 0) {
    return { label: "active", className: "border-cyan-500/30 text-cyan-700 dark:text-cyan-300" };
  }
  if (statusCount(row, "queued") > 0) return { label: "queued", className: "" };
  if (completed > 0) {
    return { label: "healthy", className: "border-emerald-500/30 text-emerald-700 dark:text-emerald-300" };
  }
  return { label: "inactive", className: "" };
}

function healthSeverity(row: ModuleHealth) {
  const failed = statusCount(row, "failed");
  const completed = statusCount(row, "completed");
  if (failed > 0 && completed === 0) return 0;
  if (failed > 0 || statusCount(row, "blocked") > 0) return 1;
  if (statusCount(row, "running") > 0 || statusCount(row, "retry_wait") > 0) return 2;
  if (statusCount(row, "queued") > 0) return 3;
  if (completed > 0) return 4;
  return 5;
}

function taskTotal(row: ModuleHealth) {
  return row.tasks_total;
}

function formatDuration(seconds?: number | null) {
  if (seconds === undefined || seconds === null) return "—";
  if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
  if (seconds < 60) return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
  return `${(seconds / 60).toFixed(1)}m`;
}

function WarningRow({
  tone,
  children,
}: {
  tone: "warning" | "danger" | "neutral";
  children: ReactNode;
}) {
  const style =
    tone === "danger"
      ? "border-rose-500/25 bg-rose-500/5 text-rose-700 dark:text-rose-300"
      : tone === "warning"
        ? "border-amber-500/25 bg-amber-500/5 text-amber-800 dark:text-amber-300"
        : "border-border/70 bg-secondary/20 text-muted-foreground";
  return (
    <li className={`flex gap-2 rounded-lg border p-3 text-xs leading-relaxed ${style}`}>
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>{children}</span>
    </li>
  );
}

export function ResultQuality({
  summary,
  taskSample,
  loading,
  error,
  scanIsLive = false,
}: {
  summary?: ScanKnowledgeSummary;
  taskSample?: TaskList;
  loading: boolean;
  error?: Error | null;
  scanIsLive?: boolean;
}) {
  const sampledQuality = inspectTaskQuality(taskSample);
  const hasServerCompleteness = summary?.completeness !== undefined && summary.completeness !== null;
  const quality = summary?.completeness
    ? {
        sampled: summary.completeness.tasks_inspected,
        total: summary.completeness.tasks_total,
        discoveryBoundTasks: summary.completeness.discovery_truncated_tasks,
        evidenceBoundTasks: summary.completeness.evidence_truncated_tasks,
        rejectedEmissions: summary.completeness.validation_rejections,
      }
    : sampledQuality;
  const truncatedTasks = summary?.completeness?.truncated_tasks;
  const hasDetailedYield = summary?.source_yield !== undefined;
  const hasAggregateHealth = summary?.module_health !== undefined;
  const sourceRows = (summary?.source_yield ?? fallbackSourceYield(summary))
    .slice()
    .sort(
      (left, right) =>
        right.exclusive_assets - left.exclusive_assets ||
        right.distinct_assets - left.distinct_assets ||
        right.observations - left.observations,
    );
  const healthRows = (summary?.module_health ?? fallbackHealth(taskSample))
    .slice()
    .sort(
      (left, right) =>
        healthSeverity(left) - healthSeverity(right) ||
        taskTotal(right) - taskTotal(left) ||
        left.module_name.localeCompare(right.module_name),
    );
  const positiveSources = sourceRows.filter((source) => source.observations > 0);
  const shownPositiveSources = positiveSources.slice(0, 12);
  const zeroYieldSources = sourceRows.filter((source) => source.observations === 0);
  const shownSources = [...shownPositiveSources, ...zeroYieldSources];
  const hasQualityWarning =
    quality.discoveryBoundTasks > 0 ||
    quality.evidenceBoundTasks > 0 ||
    quality.rejectedEmissions > 0 ||
    quality.sampled < quality.total;

  if (loading && !summary) {
    return (
      <Card aria-live="polite" aria-busy="true">
        <CardContent className="p-8 text-center text-sm text-muted-foreground">
          Loading provenance yield and execution health…
        </CardContent>
      </Card>
    );
  }

  return (
    <section aria-labelledby="result-quality-title" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="result-quality-title" className="text-lg font-semibold">
            Discovery quality
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Source contribution, unique yield, execution health, and explicit completeness limits.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          {scanIsLive && <Badge variant="outline">live · still changing</Badge>}
          <Badge variant="outline">
            {summary?.observations_total.toLocaleString() ?? 0} observations
          </Badge>
          <Badge variant="outline">{healthRows.length} modules tracked</Badge>
        </div>
      </div>

      {error && !hasServerCompleteness && (
        <div
          role="alert"
          className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-700 dark:text-rose-300"
        >
          Task-level quality signals could not be inspected: {error.message}. Aggregate
          provenance and module health remain available.
        </div>
      )}

      <div className="grid gap-4 xl:grid-cols-[1.05fr_.95fr]">
        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <DatabaseZap className="h-4 w-4 text-cyan-500" aria-hidden="true" />
                Source and provider yield
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                Ranked by exclusive assets, then distinct assets and observations.
              </p>
            </div>
            {!hasDetailedYield && summary && (
              <Badge variant="outline">module totals</Badge>
            )}
          </CardHeader>
          <CardContent>
            {shownSources.length ? (
              <div className="overflow-x-auto rounded-xl border border-border/70">
                <table className="w-full min-w-[620px] text-left text-xs">
                  <thead className="bg-secondary/35 text-[10px] uppercase tracking-wider text-muted-foreground">
                    <tr>
                      <th scope="col" className="px-3 py-2.5 font-medium">Source</th>
                      <th scope="col" className="px-3 py-2.5 text-right font-medium">Observations</th>
                      <th scope="col" className="px-3 py-2.5 text-right font-medium">Assets</th>
                      <th scope="col" className="px-3 py-2.5 text-right font-medium">Exclusive</th>
                      <th scope="col" className="px-3 py-2.5 text-right font-medium">Confidence</th>
                      <th scope="col" className="px-3 py-2.5 text-right font-medium">Last seen</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border/60">
                    {shownSources.map((source) => (
                      <tr key={`${source.source_module}:${source.source_name ?? "module"}`}>
                        <th scope="row" className="max-w-56 px-3 py-3 font-normal">
                          <span className="block break-all font-mono text-foreground">
                            {source.source_name ?? source.source_module}
                          </span>
                          {source.source_name && (
                            <span className="mt-0.5 block break-all text-[10px] text-muted-foreground">
                              via {source.source_module}
                            </span>
                          )}
                          {!source.source_name && source.observations === 0 && (
                            <span className="mt-0.5 block text-[10px] text-amber-700 dark:text-amber-300">
                              completed module · zero persisted yield
                            </span>
                          )}
                        </th>
                        <td className="px-3 py-3 text-right tabular-nums">{source.observations.toLocaleString()}</td>
                        <td className="px-3 py-3 text-right tabular-nums">{hasDetailedYield ? source.distinct_assets.toLocaleString() : "—"}</td>
                        <td className="px-3 py-3 text-right tabular-nums text-emerald-700 dark:text-emerald-300">{hasDetailedYield ? source.exclusive_assets.toLocaleString() : "—"}</td>
                        <td className="px-3 py-3 text-right tabular-nums">{hasDetailedYield ? `${Math.round(source.average_confidence * 100)}%` : "—"}</td>
                        <td className="whitespace-nowrap px-3 py-3 text-right text-muted-foreground">{source.last_observed_at ? formatRelative(source.last_observed_at) : "—"}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <div className="py-12 text-center">
                <DatabaseZap className="mx-auto mb-3 h-6 w-6 text-muted-foreground" aria-hidden="true" />
                <p className="text-sm text-muted-foreground">
                  {scanIsLive
                    ? "No provenance has been persisted yet. Sources will appear as discoveries arrive."
                    : "This scan did not persist any provenance observations."}
                </p>
              </div>
            )}
            {positiveSources.length > shownPositiveSources.length && (
              <p className="mt-3 text-xs text-muted-foreground">
                Showing the 12 highest-yield sources plus every completed zero-yield module; {positiveSources.length - shownPositiveSources.length} lower-yield source(s) are summarized out of this view.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
            <div>
              <CardTitle className="flex items-center gap-2 text-base">
                <ShieldAlert className="h-4 w-4 text-amber-500" aria-hidden="true" />
                Completeness and evidence
              </CardTitle>
              <p className="mt-1 text-xs text-muted-foreground">
                {hasServerCompleteness
                  ? "Exact scan totals aggregated from every task output summary."
                  : "Signals reported by the available bounded task sample."}
              </p>
            </div>
            <Badge variant="outline">
              {quality.sampled.toLocaleString()}/{quality.total.toLocaleString()} {hasServerCompleteness ? "tasks aggregated" : "inspected"}
            </Badge>
          </CardHeader>
          <CardContent>
            <ul className="space-y-2" aria-live="polite">
              {quality.discoveryBoundTasks > 0 && (
                <WarningRow tone="warning">
                  <strong>{quality.discoveryBoundTasks.toLocaleString()} task(s)</strong> reported
                  bounded pagination, source responses, response bodies, or process output. Their
                  discovery counts may be incomplete.
                </WarningRow>
              )}
              {quality.evidenceBoundTasks > 0 && (
                <WarningRow tone="neutral">
                  Raw evidence retention was truncated for <strong>{quality.evidenceBoundTasks.toLocaleString()} task(s)</strong>.
                  Normalized results were retained, but the downloadable debugging evidence is partial.
                </WarningRow>
              )}
              {quality.rejectedEmissions > 0 && (
                <WarningRow tone="danger">
                  Normalization rejected <strong>{quality.rejectedEmissions.toLocaleString()} malformed emission(s)</strong> from modules.
                  Review task validation errors before trusting coverage.
                </WarningRow>
              )}
              {quality.sampled < quality.total && (
                <WarningRow tone="neutral">
                  Quality inspection is bounded to the first {quality.sampled.toLocaleString()} of {quality.total.toLocaleString()} tasks.
                  Aggregate source yield and module health cover the full scan.
                </WarningRow>
              )}
            </ul>
            {truncatedTasks !== undefined && truncatedTasks > 0 && (
              <p className="mt-3 text-[11px] text-muted-foreground">
                {truncatedTasks.toLocaleString()} unique task(s) reported at least one discovery or evidence-retention truncation signal.
              </p>
            )}
            {(hasServerCompleteness || taskSample) && quality.total > 0 && !hasQualityWarning && (!error || hasServerCompleteness) && (
              <div className="flex gap-3 rounded-xl border border-emerald-500/25 bg-emerald-500/5 p-4 text-sm text-emerald-800 dark:text-emerald-300">
                <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                <p>
                  No truncation, retention-budget, or validation-rejection signals were reported
                  by the inspected task summaries.
                </p>
              </div>
            )}
            {!hasServerCompleteness && !taskSample && !error && (
              <p
                className="py-8 text-center text-sm text-muted-foreground"
                role={loading ? "status" : undefined}
              >
                {loading
                  ? "Inspecting bounded task output metadata…"
                  : "Task quality metadata is not available yet."}
              </p>
            )}
            {(hasServerCompleteness || taskSample) && quality.total === 0 && (
              <p className="py-8 text-center text-sm text-muted-foreground">
                {scanIsLive
                  ? "No task output summaries are available to inspect yet."
                  : "This scan has no task output summaries to inspect."}
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <HeartPulse className="h-4 w-4 text-violet-500" aria-hidden="true" />
              Module execution health
            </CardTitle>
            <p className="mt-1 text-xs text-muted-foreground">
              Failures and blocked work sort first. Latency is avg / p95 over the server-bounded latest finished-task sample.
            </p>
          </div>
          {!hasAggregateHealth && summary && <Badge variant="outline">task sample</Badge>}
        </CardHeader>
        <CardContent>
          {healthRows.length ? (
            <div className="max-h-[440px] overflow-auto rounded-xl border border-border/70">
              <table className="w-full min-w-[980px] text-left text-xs">
                <thead className="sticky top-0 z-10 bg-secondary text-[10px] uppercase tracking-wider text-muted-foreground">
                  <tr>
                    <th scope="col" className="px-3 py-2.5 font-medium">Module</th>
                    <th scope="col" className="px-3 py-2.5 font-medium">Health</th>
                    <th scope="col" className="px-3 py-2.5 text-right font-medium">Completed</th>
                    <th scope="col" className="px-3 py-2.5 text-right font-medium">Failed</th>
                    <th scope="col" className="px-3 py-2.5 text-right font-medium">Blocked / retry</th>
                    <th scope="col" className="px-3 py-2.5 text-right font-medium">Failure rate</th>
                    <th scope="col" className="px-3 py-2.5 text-right font-medium">Avg / p95</th>
                    <th scope="col" className="px-3 py-2.5 font-medium">Stable error codes</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border/60">
                  {healthRows.map((row) => {
                    const state = moduleState(row);
                    const completed = statusCount(row, "completed");
                    const failed = statusCount(row, "failed");
                    const blocked = statusCount(row, "blocked");
                    const retryWait = statusCount(row, "retry_wait");
                    const errorCodes = Object.entries(row.error_codes ?? {}).sort(
                      ([leftCode, leftCount], [rightCode, rightCount]) =>
                        rightCount - leftCount || leftCode.localeCompare(rightCode),
                    );
                    const durationSampleSize = row.duration_sample_size ?? 0;
                    const durationTotal = row.duration_total ?? 0;
                    return (
                      <tr key={`${row.module_name}:${row.capability}`}>
                        <th scope="row" className="max-w-72 px-3 py-3 font-normal">
                          <span className="block break-all font-mono text-foreground">{row.module_name}</span>
                          <span className="mt-0.5 block break-all text-[10px] text-muted-foreground">{row.capability}</span>
                        </th>
                        <td className="px-3 py-3"><Badge variant="outline" className={state.className}>{state.label}</Badge></td>
                        <td className="px-3 py-3 text-right tabular-nums">{completed.toLocaleString()} / {taskTotal(row).toLocaleString()}</td>
                        <td className={`px-3 py-3 text-right tabular-nums ${failed ? "font-medium text-rose-700 dark:text-rose-300" : ""}`}>{failed.toLocaleString()}</td>
                        <td className={`px-3 py-3 text-right tabular-nums ${blocked + retryWait ? "font-medium text-amber-700 dark:text-amber-300" : ""}`}>{blocked.toLocaleString()} / {retryWait.toLocaleString()}</td>
                        <td className={`whitespace-nowrap px-3 py-3 text-right tabular-nums ${row.failure_rate > 0 ? "text-rose-700 dark:text-rose-300" : "text-muted-foreground"}`}>{Math.round(row.failure_rate * 100)}%</td>
                        <td className="whitespace-nowrap px-3 py-3 text-right tabular-nums">
                          <span>{formatDuration(row.average_duration_seconds)} / {formatDuration(row.p95_duration_seconds)}</span>
                          {durationSampleSize > 0 && (
                            <span className="mt-0.5 block text-[10px] text-muted-foreground">
                              {durationSampleSize.toLocaleString()}/{durationTotal.toLocaleString()} timings
                            </span>
                          )}
                        </td>
                        <td className="max-w-72 px-3 py-3">
                          {errorCodes.length ? (
                            <div className="flex flex-wrap gap-1">
                              {errorCodes.map(([code, count]) => (
                                <Badge key={code} variant="outline" className="font-mono text-[10px] font-normal text-rose-700 dark:text-rose-300">
                                  {code} ×{count.toLocaleString()}
                                </Badge>
                              ))}
                            </div>
                          ) : (
                            <span className="text-muted-foreground">—</span>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="py-12 text-center">
              <Clock3 className="mx-auto mb-3 h-6 w-6 text-muted-foreground" aria-hidden="true" />
              <p className="text-sm text-muted-foreground">
                {scanIsLive ? "No module tasks have started yet." : "No module execution history is available."}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
    </section>
  );
}
