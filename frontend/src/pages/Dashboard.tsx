import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Activity,
  ArrowRight,
  Boxes,
  CheckCircle2,
  CircleAlert,
  Clock,
  GitBranch,
  Network,
  Plus,
  Radar,
  Timer,
  XCircle,
} from "lucide-react";

import { DistributionBars } from "@/components/DistributionBars";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { api } from "@/lib/api";
import { formatRelative } from "@/lib/utils";

function fmtDuration(seconds: number | null | undefined) {
  if (!seconds) return "—";
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 3600) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export function Dashboard() {
  const stats = useQuery({ queryKey: ["stats"], queryFn: api.stats, refetchInterval: 5000 });
  const recent = useQuery({
    queryKey: ["recent-targets"],
    queryFn: () => api.listTargets({ page: 1, page_size: 8 }),
    refetchInterval: () => ((stats.data?.running ?? 0) + (stats.data?.queued ?? 0) > 0 ? 5000 : false),
  });
  const knowledge = useQuery({
    queryKey: ["knowledge-stats"],
    queryFn: api.knowledgeStats,
    refetchInterval: () => ((stats.data?.running ?? 0) + (stats.data?.queued ?? 0) > 0 ? 5000 : false),
  });
  const modules = useQuery({ queryKey: ["modules"], queryFn: api.modules });
  const system = useQuery({ queryKey: ["system-info"], queryFn: api.systemInfo });

  const unavailable = modules.data?.filter((module) => !module.available).length ?? 0;
  const activeScans = (stats.data?.running ?? 0) + (stats.data?.queued ?? 0);
  const cards = [
    { label: "Queued", value: stats.data?.queued ?? 0, icon: Clock, color: "text-cyan-600 dark:text-cyan-400" },
    { label: "Running", value: stats.data?.running ?? 0, icon: Activity, color: "text-amber-600 dark:text-amber-400" },
    { label: "Completed", value: stats.data?.completed ?? 0, icon: CheckCircle2, color: "text-emerald-600 dark:text-emerald-400" },
    { label: "Failed", value: stats.data?.failed ?? 0, icon: CircleAlert, color: "text-rose-600 dark:text-rose-400" },
    { label: "Cancelled", value: stats.data?.cancelled ?? 0, icon: XCircle, color: "text-slate-400" },
    { label: "Avg duration", value: fmtDuration(stats.data?.avg_duration_seconds), icon: Timer, color: "text-violet-400" },
  ];

  return (
    <div className="space-y-7">
      {[stats, recent, knowledge, modules].some((query) => query.isError) && <Card className="border-rose-500/30"><CardContent className="py-3 text-sm text-rose-600 dark:text-rose-400">Dashboard data could not be fully loaded. Existing values may be stale; use the deployment key in Settings, then retry.</CardContent></Card>}
      <section className="surface-hero relative overflow-hidden rounded-2xl border border-border/70 p-6 sm:p-8">
        <div className="relative z-10 flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-2xl">
            <div className="mb-4 inline-flex items-center gap-2 rounded-full border border-primary/20 bg-primary/5 px-3 py-1 text-xs text-primary">
              <Radar className="h-3.5 w-3.5" /> Recon intelligence control plane
            </div>
            <h1 className="text-3xl font-semibold tracking-tight sm:text-4xl">
              Attack surface, continuously understood.
            </h1>
            <p className="mt-3 max-w-xl text-sm leading-relaxed text-muted-foreground">
              Follow discoveries as they become normalized assets, evidence-backed relationships, and deduplicated next actions.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button asChild variant="outline"><Link to="/modules"><Radar /> Explore capabilities</Link></Button>
            <Button asChild><Link to="/targets"><Plus /> Authorized scan</Link></Button>
          </div>
        </div>
        <div className="relative z-10 mt-7 flex flex-wrap gap-3 text-xs text-muted-foreground">
          <span className="inline-flex items-center gap-2 rounded-full bg-background/60 px-3 py-1.5"><span className="h-2 w-2 rounded-full bg-emerald-400" /> {system.data?.env ?? "runtime"}</span>
          <span className="inline-flex items-center gap-2 rounded-full bg-background/60 px-3 py-1.5">{activeScans} active scans</span>
          <span className="inline-flex items-center gap-2 rounded-full bg-background/60 px-3 py-1.5">{modules.data?.length ?? 0} implementations</span>
          {unavailable > 0 && <span className="inline-flex items-center gap-2 rounded-full bg-amber-400/10 px-3 py-1.5 text-amber-400">{unavailable} unavailable</span>}
        </div>
      </section>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {cards.map((card) => (
          <Card key={card.label} className="metric-card">
            <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-xs font-medium text-muted-foreground">{card.label}</CardTitle>
              <card.icon className={`h-4 w-4 ${card.color}`} />
            </CardHeader>
            <CardContent><div className="text-2xl font-semibold tabular-nums">{card.value}</div></CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-[1.1fr_.9fr]">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div><CardTitle>Knowledge base</CardTitle><p className="mt-1 text-xs text-muted-foreground">Persistent intelligence across every scan</p></div>
            <Boxes className="h-5 w-5 text-cyan-400" />
          </CardHeader>
          <CardContent>
            <div className="mb-6 grid grid-cols-3 divide-x divide-border rounded-xl border border-border/70 bg-secondary/20 py-4 text-center">
              <div><p className="text-xl font-semibold tabular-nums">{knowledge.data?.assets_total.toLocaleString() ?? 0}</p><p className="mt-1 text-[11px] text-muted-foreground">Assets</p></div>
              <div><p className="text-xl font-semibold tabular-nums">{knowledge.data?.relationships_total.toLocaleString() ?? 0}</p><p className="mt-1 text-[11px] text-muted-foreground">Relationships</p></div>
              <div><p className="text-xl font-semibold tabular-nums">{knowledge.data?.observations_total.toLocaleString() ?? 0}</p><p className="mt-1 text-[11px] text-muted-foreground">Observations</p></div>
            </div>
            <DistributionBars values={knowledge.data?.assets_by_kind} limit={10} empty="Discovery data will appear here." />
          </CardContent>
        </Card>

        <Card>
          <CardHeader><CardTitle className="flex items-center gap-2"><GitBranch className="h-5 w-5 text-violet-400" /> Task pipeline</CardTitle></CardHeader>
          <CardContent className="space-y-6">
            <DistributionBars values={knowledge.data?.tasks_by_status} limit={10} empty="No task history yet." />
            <div className="rounded-xl border border-border/70 bg-secondary/20 p-4">
              <div className="flex items-center gap-3"><Network className="h-5 w-5 text-primary" /><div><p className="text-sm font-medium">Result-driven execution</p><p className="mt-1 text-xs leading-relaxed text-muted-foreground">Every new normalized entity can activate relevant capability consumers while identity, scope, and cache policy prevent redundant work.</p></div></div>
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div><CardTitle>Recent scans</CardTitle><p className="mt-1 text-xs text-muted-foreground">Latest authorized discovery activity</p></div>
          <Button asChild variant="ghost" size="sm"><Link to="/targets">View all <ArrowRight /></Link></Button>
        </CardHeader>
        <CardContent>
          {recent.data?.items.length ? (
            <div className="grid gap-2 md:grid-cols-2">
              {recent.data.items.map((target) => (
                <Link key={target.id} to={`/targets/${target.id}`} className="group flex items-center justify-between gap-3 rounded-xl border border-border/70 p-4 transition-colors hover:border-primary/30 hover:bg-secondary/25">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2"><Badge variant="outline">#{target.id}</Badge><span className="truncate font-mono text-sm group-hover:text-primary">{target.url}</span></div>
                    <div className="mt-2 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground"><span>{target.target_kind.replaceAll("_", " ")}</span><span>·</span><span>{target.profile}</span><span>·</span><span>{formatRelative(target.created_at)}</span>{target.tags.slice(0, 2).map((tag) => <Badge key={tag} variant="outline" className="text-[9px]">{tag}</Badge>)}</div>
                  </div>
                  <StatusBadge status={target.status} />
                </Link>
              ))}
            </div>
          ) : (
            <div className="py-12 text-center"><Radar className="mx-auto mb-3 h-8 w-8 text-muted-foreground" /><p className="text-sm text-muted-foreground">No scans yet. Start with an explicitly authorized target.</p></div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
