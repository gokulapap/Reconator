import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Activity,
  CheckCircle2,
  CircleAlert,
  Clock,
  ListChecks,
  Timer,
  XCircle,
} from "lucide-react";

import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { StatusBadge } from "@/components/StatusBadge";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { formatRelative } from "@/lib/utils";

function fmtDuration(s: number | null | undefined) {
  if (!s) return "—";
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

export function Dashboard() {
  const stats = useQuery({
    queryKey: ["stats"],
    queryFn: api.stats,
    refetchInterval: 5000,
  });
  const recent = useQuery({
    queryKey: ["recent-targets"],
    queryFn: () => api.listTargets({ page: 1, page_size: 8 }),
    refetchInterval: 5000,
  });
  const knowledge = useQuery({
    queryKey: ["knowledge-stats"],
    queryFn: api.knowledgeStats,
    refetchInterval: 5000,
  });

  const cards = [
    { label: "Queued", value: stats.data?.queued ?? 0, icon: Clock, color: "text-cyan-400" },
    { label: "Running", value: stats.data?.running ?? 0, icon: Activity, color: "text-amber-400" },
    { label: "Completed", value: stats.data?.completed ?? 0, icon: CheckCircle2, color: "text-emerald-400" },
    { label: "Failed", value: stats.data?.failed ?? 0, icon: CircleAlert, color: "text-rose-400" },
    { label: "Cancelled", value: stats.data?.cancelled ?? 0, icon: XCircle, color: "text-slate-400" },
    {
      label: "Avg duration",
      value: fmtDuration(stats.data?.avg_duration_seconds),
      icon: Timer,
      color: "text-violet-400",
    },
  ];

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Recon queue health and recent activity.
          </p>
        </div>
        <Button asChild>
          <Link to="/targets">
            <ListChecks /> Manage targets
          </Link>
        </Button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {cards.map((c) => (
          <Card key={c.label}>
            <CardHeader className="flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium text-muted-foreground">
                {c.label}
              </CardTitle>
              <c.icon className={`h-4 w-4 ${c.color}`} />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-semibold">{c.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="grid gap-4 sm:grid-cols-3">
        <Card><CardContent className="pt-5"><div className="text-2xl font-semibold">{knowledge.data?.assets_total ?? 0}</div><p className="text-xs text-muted-foreground">Persistent graph assets</p></CardContent></Card>
        <Card><CardContent className="pt-5"><div className="text-2xl font-semibold">{knowledge.data?.relationships_total ?? 0}</div><p className="text-xs text-muted-foreground">Correlated relationships</p></CardContent></Card>
        <Card><CardContent className="pt-5"><div className="text-2xl font-semibold">{knowledge.data?.observations_total ?? 0}</div><p className="text-xs text-muted-foreground">Provenance observations</p></CardContent></Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recent targets</CardTitle>
        </CardHeader>
        <CardContent>
          {recent.data?.items.length ? (
            <ul className="divide-y divide-border">
              {recent.data.items.map((t) => (
                <li key={t.id} className="py-3 flex items-center justify-between gap-3">
                  <div className="min-w-0 flex-1">
                    <Link
                      to={`/targets/${t.id}`}
                      className="font-mono text-sm hover:text-primary truncate inline-block max-w-full align-middle"
                    >
                      {t.url}
                    </Link>
                    {(t.tags || []).length > 0 && (
                      <span className="ml-2 inline-flex gap-1 align-middle">
                        {t.tags.map((tg) => (
                          <Badge key={tg} variant="outline" className="text-[10px]">
                            {tg}
                          </Badge>
                        ))}
                      </span>
                    )}
                  </div>
                  <div className="flex items-center gap-3 shrink-0">
                    <span className="text-xs text-muted-foreground">
                      {formatRelative(t.created_at)}
                    </span>
                    <StatusBadge status={t.status} />
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-sm text-muted-foreground">No targets yet.</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
