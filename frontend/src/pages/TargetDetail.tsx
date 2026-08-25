import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Ban, Download, Network, RefreshCcw, Search } from "lucide-react";

import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/StatusBadge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { formatRelative } from "@/lib/utils";

function highlight(text: string, query: string) {
  if (!query) return text;
  const lower = text.toLowerCase();
  const q = query.toLowerCase();
  const out: (string | JSX.Element)[] = [];
  let i = 0;
  while (i < text.length) {
    const idx = lower.indexOf(q, i);
    if (idx < 0) {
      out.push(text.slice(i));
      break;
    }
    if (idx > i) out.push(text.slice(i, idx));
    out.push(
      <mark
        key={idx}
        className="bg-amber-400/30 text-foreground rounded-sm"
      >
        {text.slice(idx, idx + q.length)}
      </mark>,
    );
    i = idx + q.length;
  }
  return <>{out}</>;
}

export function TargetDetail() {
  const { id } = useParams<{ id: string }>();
  const targetId = Number(id);
  const qc = useQueryClient();
  const { toast } = useToast();
  const nav = useNavigate();
  const [active, setActive] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [activeTask, setActiveTask] = useState<number | null>(null);
  const [scopePattern, setScopePattern] = useState("");
  const [scopeAction, setScopeAction] = useState<"include" | "exclude">("exclude");
  const [scopeType, setScopeType] = useState<"exact" | "subdomain" | "cidr" | "url_prefix" | "regex">("exact");

  const detail = useQuery({
    queryKey: ["target", targetId],
    queryFn: () => api.getTarget(targetId),
    refetchInterval: (q) => {
      const s = q.state.data?.status;
      return s === "queued" || s === "running" ? 5000 : false;
    },
  });

  const result = useQuery({
    queryKey: ["result", targetId, active],
    queryFn: () => api.getResult(targetId, active!),
    enabled: !!active,
  });

  const assets = useQuery({
    queryKey: ["assets", targetId],
    queryFn: () => api.listAssets(targetId),
    refetchInterval: 5000,
  });

  const graph = useQuery({
    queryKey: ["graph", targetId],
    queryFn: () => api.getGraph(targetId),
    refetchInterval: 5000,
  });

  const tasks = useQuery({
    queryKey: ["tasks", targetId],
    queryFn: () => api.listTasks(targetId),
    refetchInterval: 3000,
  });

  const taskDetail = useQuery({
    queryKey: ["task", targetId, activeTask],
    queryFn: () => api.getTask(targetId, activeTask!),
    enabled: activeTask !== null,
    refetchInterval: 3000,
  });

  const events = useQuery({
    queryKey: ["events", targetId],
    queryFn: () => api.listEvents(targetId),
    refetchInterval: 3000,
  });

  const scope = useQuery({
    queryKey: ["scope", targetId],
    queryFn: () => api.listScope(targetId),
  });

  const comparison = useQuery({
    queryKey: ["comparison", targetId, detail.data?.parent_target_id],
    queryFn: () => api.compareScans(targetId, detail.data!.parent_target_id!),
    enabled: !!detail.data?.parent_target_id,
  });

  const addScope = useMutation({
    mutationFn: () => api.addScope(targetId, { action: scopeAction, rule_type: scopeType, pattern: scopePattern }),
    onSuccess: () => {
      setScopePattern("");
      toast({ title: "Scope updated", description: "Queued work was reconciled with the new policy." });
      qc.invalidateQueries({ queryKey: ["scope", targetId] });
      qc.invalidateQueries({ queryKey: ["tasks", targetId] });
      qc.invalidateQueries({ queryKey: ["target", targetId] });
    },
    onError: (e: Error) => toast({ variant: "destructive", title: "Scope update failed", description: e.message }),
  });

  const deleteScope = useMutation({
    mutationFn: (ruleId: number) => api.deleteScope(targetId, ruleId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scope", targetId] });
      qc.invalidateQueries({ queryKey: ["tasks", targetId] });
    },
    onError: (e: Error) => toast({ variant: "destructive", title: "Scope update failed", description: e.message }),
  });

  const cancel = useMutation({
    mutationFn: () => api.cancelTarget(targetId),
    onSuccess: () => {
      toast({ title: "Cancellation requested" });
      qc.invalidateQueries({ queryKey: ["target", targetId] });
    },
    onError: (e: Error) =>
      toast({ variant: "destructive", title: "Failed", description: e.message }),
  });

  const rescan = useMutation({
    mutationFn: () => api.rescanTarget(targetId),
    onSuccess: (t) => {
      toast({ title: "Rescan queued", description: `New target #${t.id}` });
      nav(`/targets/${t.id}`);
    },
    onError: (e: Error) =>
      toast({ variant: "destructive", title: "Failed", description: e.message }),
  });

  const filteredOutput = useMemo(() => {
    const out = result.data?.output ?? "";
    if (!filter) return out;
    return out
      .split(/\r?\n/)
      .filter((line) => line.toLowerCase().includes(filter.toLowerCase()))
      .join("\n");
  }, [result.data, filter]);

  if (detail.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading…</p>;
  }
  if (!detail.data) {
    return <p className="text-sm text-rose-400">Target not found.</p>;
  }

  const t = detail.data;
  const canCancel = t.status === "queued" || t.status === "running";
  const graphNodes = new Map(graph.data?.nodes.map((node) => [node.id, node]) ?? []);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4 flex-wrap">
        <div className="flex items-center gap-3">
          <Button asChild size="icon" variant="ghost">
            <Link to="/targets">
              <ArrowLeft />
            </Link>
          </Button>
          <div>
            <h1 className="text-2xl font-semibold font-mono">{t.url}</h1>
            <p className="text-xs text-muted-foreground">
              Queued {formatRelative(t.created_at)} · Started{" "}
              {formatRelative(t.started_at)} · Completed{" "}
              {formatRelative(t.completed_at)}
            </p>
            {(t.tags || []).length > 0 && (
              <div className="flex gap-1 mt-1">
                {t.tags.map((tg) => (
                  <Badge key={tg} variant="outline">
                    {tg}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2">
          <StatusBadge status={t.status} />
          <Badge variant="outline">{t.profile}</Badge>
          {canCancel && (
            <Button
              size="sm"
              variant="outline"
              onClick={() => cancel.mutate()}
              disabled={cancel.isPending}
            >
              <Ban /> Cancel
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => rescan.mutate()}
            disabled={rescan.isPending || canCancel}
            title={canCancel ? "Wait for this scan to finish or cancel it first" : "Create an incremental rescan"}
          >
            <RefreshCcw /> Rescan
          </Button>
        </div>
      </div>

      {t.error && (
        <Card>
          <CardContent className="py-3 text-sm text-rose-400">
            {t.error}
          </CardContent>
        </Card>
      )}

      {comparison.data && (
        <Card>
          <CardContent className="flex flex-wrap gap-4 py-3 text-sm">
            <span>Changes since scan #{comparison.data.baseline_target_id}:</span>
            <span className="text-emerald-400">+{comparison.data.added.length} added</span>
            <span className="text-rose-400">−{comparison.data.removed.length} removed</span>
            <span className="text-amber-400">{comparison.data.changed.length} changed</span>
            <span className="text-muted-foreground">{comparison.data.unchanged_count} unchanged</span>
          </CardContent>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card><CardContent className="pt-5"><p className="text-2xl font-semibold">{assets.data?.total ?? 0}</p><p className="text-xs text-muted-foreground">Canonical assets</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-2xl font-semibold">{graph.data?.edges.length ?? 0}</p><p className="text-xs text-muted-foreground">Typed relationships{graph.data?.truncated ? "+" : ""}</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-2xl font-semibold">{tasks.data?.total ?? 0}</p><p className="text-xs text-muted-foreground">Result-driven tasks</p></CardContent></Card>
        <Card><CardContent className="pt-5"><p className="text-2xl font-semibold">{events.data?.length ?? 0}</p><p className="text-xs text-muted-foreground">Execution events</p></CardContent></Card>
      </div>

      <Tabs defaultValue="assets" className="space-y-4">
        <TabsList>
          <TabsTrigger value="assets">Assets</TabsTrigger>
          <TabsTrigger value="graph">Relationships</TabsTrigger>
          <TabsTrigger value="tasks">Tasks</TabsTrigger>
          <TabsTrigger value="events">Timeline</TabsTrigger>
          <TabsTrigger value="scope">Scope</TabsTrigger>
          {t.results.length > 0 && <TabsTrigger value="legacy">Legacy output</TabsTrigger>}
        </TabsList>

        <TabsContent value="assets">
          <Card>
            <CardHeader><CardTitle>Knowledge graph assets</CardTitle></CardHeader>
            <CardContent className="overflow-auto">
              <table className="w-full text-sm">
                <thead><tr className="border-b text-left text-muted-foreground"><th className="py-2">Kind</th><th>Canonical value</th><th>Priority</th><th>Last seen</th></tr></thead>
                <tbody>
                  {assets.data?.items.map((asset) => (
                    <tr key={asset.id} className="border-b border-border/50">
                      <td className="py-2"><Badge variant="outline">{asset.kind}</Badge></td>
                      <td className="font-mono text-xs break-all">{asset.canonical_value}</td>
                      <td>{asset.priority_score.toFixed(0)}</td>
                      <td className="text-muted-foreground">{formatRelative(asset.last_seen_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!assets.data?.items.length && <p className="text-sm text-muted-foreground">No assets observed yet.</p>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="graph">
          <Card>
            <CardHeader><CardTitle className="flex items-center gap-2"><Network className="h-5 w-5" /> Asset relationship graph</CardTitle></CardHeader>
            <CardContent className="overflow-auto">
              {graph.data?.truncated && <p className="mb-3 text-xs text-amber-400">Showing a bounded graph view. Use the API for paginated analysis.</p>}
              <table className="w-full text-sm">
                <thead><tr className="border-b text-left text-muted-foreground"><th className="py-2">Source</th><th>Relationship</th><th>Target</th><th>Confidence</th></tr></thead>
                <tbody>
                  {graph.data?.edges.map((edge) => {
                    const source = graphNodes.get(edge.source_asset_id);
                    const target = graphNodes.get(edge.target_asset_id);
                    return <tr key={edge.id} className="border-b border-border/50">
                      <td className="max-w-[320px] py-2 font-mono text-xs break-all"><Badge variant="outline" className="mr-2">{source?.kind ?? "asset"}</Badge>{source?.canonical_value ?? `#${edge.source_asset_id}`}</td>
                      <td><Badge variant="outline">{edge.relationship_type}</Badge></td>
                      <td className="max-w-[320px] font-mono text-xs break-all"><Badge variant="outline" className="mr-2">{target?.kind ?? "asset"}</Badge>{target?.canonical_value ?? `#${edge.target_asset_id}`}</td>
                      <td>{Math.round(edge.confidence * 100)}%</td>
                    </tr>;
                  })}
                </tbody>
              </table>
              {!graph.data?.edges.length && <p className="text-sm text-muted-foreground">No relationships observed yet.</p>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="tasks">
          <div className="grid gap-6 lg:grid-cols-[360px_1fr]">
            <Card><CardHeader><CardTitle>Task graph</CardTitle></CardHeader><CardContent className="px-2 max-h-[65vh] overflow-auto">
              <ul className="space-y-1">
                {tasks.data?.items.map((task) => (
                  <li key={task.id}><button onClick={() => setActiveTask(task.id)} className={`w-full rounded-md px-3 py-2 text-left ${activeTask === task.id ? "bg-secondary" : "hover:bg-secondary/60"}`}>
                    <div className="flex items-center justify-between gap-2"><span className="font-mono text-xs">{task.module_name}</span><StatusBadge status={task.status} /></div>
                    <p className="mt-1 text-xs text-muted-foreground">{task.capability} · attempt {task.attempts}/{task.max_attempts}</p>
                  </button></li>
                ))}
              </ul>
            </CardContent></Card>
            <Card><CardHeader><CardTitle className="font-mono text-base">{taskDetail.data?.module_name ?? "Select a task"}</CardTitle></CardHeader><CardContent>
              {taskDetail.data ? <div className="space-y-3">
                {taskDetail.data.error_detail && <p className="text-sm text-rose-400">{taskDetail.data.error_code}: {taskDetail.data.error_detail}</p>}
                <pre className="text-xs bg-secondary/40 rounded-md p-4 overflow-auto max-h-[50vh] whitespace-pre-wrap break-words">{taskDetail.data.raw_output || JSON.stringify(taskDetail.data.output_summary, null, 2)}</pre>
              </div> : <p className="text-sm text-muted-foreground">Select a task to inspect evidence and structured output.</p>}
            </CardContent></Card>
          </div>
        </TabsContent>

        <TabsContent value="events">
          <Card><CardHeader><CardTitle>Execution timeline</CardTitle></CardHeader><CardContent>
            <ol className="space-y-3">
              {events.data?.map((event) => <li key={event.id} className="border-l-2 border-border pl-4">
                <div className="flex items-center gap-2"><Badge variant="outline">{event.event_type}</Badge><span className="text-xs text-muted-foreground">{formatRelative(event.created_at)}</span></div>
                <p className={`mt-1 text-sm ${event.level === "error" ? "text-rose-400" : ""}`}>{event.message}</p>
              </li>)}
            </ol>
          </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="scope">
          <div className="grid gap-6 lg:grid-cols-[1fr_380px]">
            <Card>
              <CardHeader><CardTitle>Central scope policy</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {scope.data?.map((rule) => (
                  <div key={rule.id} className="flex items-center justify-between gap-3 rounded-md border border-border p-3">
                    <div className="min-w-0">
                      <div className="flex gap-2"><Badge variant={rule.action === "exclude" ? "destructive" : "outline"}>{rule.action}</Badge><Badge variant="outline">{rule.rule_type}</Badge>{rule.asset_kind && <Badge variant="outline">{rule.asset_kind}</Badge>}</div>
                      <p className="mt-2 break-all font-mono text-xs">{rule.normalized_pattern}</p>
                      {rule.reason && <p className="mt-1 text-xs text-muted-foreground">{rule.reason}</p>}
                    </div>
                    <Button size="sm" variant="ghost" onClick={() => deleteScope.mutate(rule.id)}>Delete</Button>
                  </div>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Add scope rule</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={scopeAction} onChange={(event) => setScopeAction(event.target.value as typeof scopeAction)}><option value="exclude">Exclude</option><option value="include">Include</option></select>
                <select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={scopeType} onChange={(event) => setScopeType(event.target.value as typeof scopeType)}><option value="exact">Exact host/value</option><option value="subdomain">Domain and subdomains</option><option value="cidr">CIDR range</option><option value="url_prefix">URL prefix</option><option value="regex">Safe regular expression</option></select>
                <Input value={scopePattern} onChange={(event) => setScopePattern(event.target.value)} placeholder="Pattern" />
                <p className="text-xs text-muted-foreground">Exclusions always win. Changing policy immediately reconciles unfinished and previously observed work.</p>
                <Button className="w-full" disabled={!scopePattern.trim() || addScope.isPending} onClick={() => addScope.mutate()}>Apply and reconcile</Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="legacy">
          <div className="grid gap-6 lg:grid-cols-[280px_1fr]">
            <Card><CardHeader><CardTitle>Legacy modules</CardTitle></CardHeader><CardContent className="px-2"><ul>{t.results.map((r) => <li key={r.module}><button onClick={() => setActive(r.module)} className="w-full flex items-center justify-between px-3 py-2 rounded-md hover:bg-secondary/60"><span className="font-mono text-sm">{r.module}</span><StatusBadge status={r.status} /></button></li>)}</ul></CardContent></Card>
            <Card><CardHeader className="flex-row items-center justify-between"><CardTitle className="font-mono text-base">{active ?? "Select a module"}</CardTitle>{active && <div className="flex gap-2"><div className="relative w-52"><Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" /><Input className="pl-8 h-9" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter output" /></div>{result.data?.has_output && <Button size="sm" variant="outline" onClick={() => void api.downloadResult(targetId, active)}><Download /> Download</Button>}</div>}</CardHeader><CardContent><pre className="text-xs bg-secondary/40 rounded-md p-4 overflow-auto max-h-[60vh] whitespace-pre-wrap break-words">{highlight(filteredOutput || "(empty)", filter)}</pre></CardContent></Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
