import { useMemo, useState } from "react";
import { useInfiniteQuery, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  ArrowLeft,
  Ban,
  Boxes,
  Download,
  GitCompareArrows,
  ListTree,
  RefreshCcw,
  Search,
  ShieldCheck,
  Sparkles,
} from "lucide-react";

import { api, type Asset, type ReconTaskStatus } from "@/lib/api";
import { AssetInspector } from "@/components/AssetInspector";
import { DistributionBars } from "@/components/DistributionBars";
import { GraphExplorer } from "@/components/GraphExplorer";
import { StatusBadge } from "@/components/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { formatRelative } from "@/lib/utils";

function highlight(text: string, query: string) {
  if (!query) return text;
  const lower = text.toLowerCase();
  const normalizedQuery = query.toLowerCase();
  const output: (string | JSX.Element)[] = [];
  let cursor = 0;
  while (cursor < text.length) {
    const index = lower.indexOf(normalizedQuery, cursor);
    if (index < 0) {
      output.push(text.slice(cursor));
      break;
    }
    if (index > cursor) output.push(text.slice(cursor, index));
    output.push(
      <mark key={index} className="rounded-sm bg-amber-400/30 text-foreground">
        {text.slice(index, index + normalizedQuery.length)}
      </mark>,
    );
    cursor = index + normalizedQuery.length;
  }
  return <>{output}</>;
}

function Metric({ value, label, detail }: { value: number; label: string; detail?: string }) {
  return (
    <Card className="metric-card">
      <CardContent className="p-5">
        <p className="text-2xl font-semibold tabular-nums">{value.toLocaleString()}</p>
        <p className="mt-1 text-xs font-medium text-muted-foreground">{label}</p>
        {detail && <p className="mt-2 text-[11px] text-muted-foreground/80">{detail}</p>}
      </CardContent>
    </Card>
  );
}

function AssetListRows({
  assets,
  selectedId,
  onSelect,
}: {
  assets: Asset[];
  selectedId: number | null;
  onSelect: (asset: Asset) => void;
}) {
  return (
    <div className="max-h-[680px] overflow-auto rounded-xl border border-border/70">
      {assets.map((asset) => (
        <button
          key={asset.id}
          onClick={() => onSelect(asset)}
          className={`w-full border-b border-border/50 p-3 text-left transition-colors last:border-0 ${selectedId === asset.id ? "bg-primary/10" : "hover:bg-secondary/35"}`}
        >
          <div className="flex items-center justify-between gap-3">
            <Badge variant="outline">{asset.kind}</Badge>
            <span className="text-[11px] tabular-nums text-muted-foreground">
              priority {asset.priority_score.toFixed(0)}
            </span>
          </div>
          <p className="mt-2 break-all font-mono text-xs leading-relaxed">
            {asset.canonical_value}
          </p>
          <p className="mt-1 text-[11px] text-muted-foreground">
            Seen {formatRelative(asset.last_seen_at)}
          </p>
        </button>
      ))}
      {!assets.length && (
        <p className="p-10 text-center text-sm text-muted-foreground">
          No assets match these filters.
        </p>
      )}
    </div>
  );
}

export function TargetDetail() {
  const { id } = useParams<{ id: string }>();
  const targetId = Number(id);
  const queryClient = useQueryClient();
  const { toast } = useToast();
  const navigate = useNavigate();
  const [activeLegacyModule, setActiveLegacyModule] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("overview");
  const [legacyFilter, setLegacyFilter] = useState("");
  const [activeTask, setActiveTask] = useState<number | null>(null);
  const [selectedAssetId, setSelectedAssetId] = useState<number | null>(null);
  const [assetSearch, setAssetSearch] = useState("");
  const [assetKind, setAssetKind] = useState("all");
  const [assetPriority, setAssetPriority] = useState("0");
  const [assetPage, setAssetPage] = useState(1);
  const [taskSearch, setTaskSearch] = useState("");
  const [taskStatus, setTaskStatus] = useState<"all" | ReconTaskStatus>("all");
  const [taskPage, setTaskPage] = useState(1);
  const [eventSearch, setEventSearch] = useState("");
  const [eventLevel, setEventLevel] = useState("all");
  const [scopePattern, setScopePattern] = useState("");
  const [scopeAction, setScopeAction] = useState<"include" | "exclude">("exclude");
  const [scopeType, setScopeType] = useState<
    "exact" | "subdomain" | "cidr" | "url_prefix" | "regex"
  >("exact");

  const detail = useQuery({
    queryKey: ["target", targetId],
    queryFn: ({ signal }) => api.getTarget(targetId, signal),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status ?? "") ? 5000 : false,
  });
  const scanIsLive = ["queued", "running"].includes(detail.data?.status ?? "");
  const summary = useQuery({
    queryKey: ["scan-knowledge-summary", targetId],
    queryFn: ({ signal }) => api.scanKnowledgeSummary(targetId, signal),
    refetchInterval: scanIsLive ? 5000 : false,
  });
  const assets = useQuery({
    queryKey: ["assets", targetId, assetKind, assetSearch, assetPriority, assetPage],
    queryFn: ({ signal }) =>
      api.listAssets(targetId, {
        kind: assetKind === "all" ? undefined : assetKind,
        search: assetSearch || undefined,
        min_priority: Number(assetPriority) || 0,
        page: activeTab === "overview" ? 1 : assetPage,
        page_size: activeTab === "overview" ? 8 : 100,
        signal,
      }),
    enabled: activeTab === "overview" || activeTab === "assets",
    refetchInterval: scanIsLive && activeTab === "assets" ? 5000 : false,
  });
  const assetIntelligence = useQuery({
    queryKey: ["asset-intelligence", targetId, selectedAssetId],
    queryFn: ({ signal }) =>
      api.getAssetIntelligence(targetId, selectedAssetId!, signal),
    enabled:
      selectedAssetId !== null && ["overview", "assets", "graph"].includes(activeTab),
  });
  const graph = useQuery({
    queryKey: ["graph", targetId],
    queryFn: ({ signal }) => api.getGraph(targetId, 1000, signal),
    enabled: activeTab === "graph",
    refetchInterval: scanIsLive && activeTab === "graph" ? 5000 : false,
  });
  const tasks = useQuery({
    queryKey: ["tasks", targetId, taskPage],
    queryFn: ({ signal }) =>
      api.listTasks(targetId, { page: taskPage, page_size: 100, signal }),
    enabled: activeTab === "tasks",
    refetchInterval: scanIsLive && activeTab === "tasks" ? 3000 : false,
  });
  const taskDetail = useQuery({
    queryKey: ["task", targetId, activeTask],
    queryFn: ({ signal }) => api.getTask(targetId, activeTask!, signal),
    enabled: activeTab === "tasks" && activeTask !== null,
    refetchInterval: scanIsLive && activeTab === "tasks" ? 3000 : false,
  });
  const events = useInfiniteQuery({
    queryKey: ["events", targetId],
    queryFn: ({ pageParam, signal }) => api.listEvents(targetId, pageParam, signal),
    initialPageParam: 0,
    getNextPageParam: (lastPage) =>
      lastPage.length === 500 ? lastPage[lastPage.length - 1].id : undefined,
    enabled: activeTab === "events",
    refetchInterval: scanIsLive && activeTab === "events" ? 3000 : false,
  });
  const scope = useQuery({
    queryKey: ["scope", targetId],
    queryFn: () => api.listScope(targetId),
    enabled: activeTab === "scope",
  });
  const legacyResult = useQuery({
    queryKey: ["result", targetId, activeLegacyModule],
    queryFn: () => api.getResult(targetId, activeLegacyModule!),
    enabled: activeTab === "legacy" && !!activeLegacyModule,
  });
  const comparison = useQuery({
    queryKey: ["comparison", targetId, detail.data?.parent_target_id],
    queryFn: () => api.compareScans(targetId, detail.data!.parent_target_id!),
    enabled:
      !!detail.data?.parent_target_id && ["overview", "changes"].includes(activeTab),
  });

  const eventHistory = useMemo(() => {
    const merged = new Map(
      (events.data?.pages.flat() ?? []).map((event) => [event.id, event]),
    );
    return [...merged.values()].sort((left, right) => left.id - right.id).slice(-2000);
  }, [events.data?.pages]);

  const addScope = useMutation({
    mutationFn: () =>
      api.addScope(targetId, {
        action: scopeAction,
        rule_type: scopeType,
        pattern: scopePattern,
      }),
    onSuccess: () => {
      setScopePattern("");
      toast({
        title: "Scope updated",
        description: "Queued work was reconciled with the new policy.",
      });
      queryClient.invalidateQueries({ queryKey: ["scope", targetId] });
      queryClient.invalidateQueries({ queryKey: ["tasks", targetId] });
      queryClient.invalidateQueries({ queryKey: ["target", targetId] });
    },
    onError: (error: Error) =>
      toast({ variant: "destructive", title: "Scope update failed", description: error.message }),
  });
  const deleteScope = useMutation({
    mutationFn: (ruleId: number) => api.deleteScope(targetId, ruleId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["scope", targetId] });
      queryClient.invalidateQueries({ queryKey: ["tasks", targetId] });
    },
    onError: (error: Error) =>
      toast({ variant: "destructive", title: "Scope update failed", description: error.message }),
  });
  const cancel = useMutation({
    mutationFn: () => api.cancelTarget(targetId),
    onSuccess: () => {
      toast({ title: "Cancellation requested" });
      queryClient.invalidateQueries({ queryKey: ["target", targetId] });
    },
    onError: (error: Error) =>
      toast({ variant: "destructive", title: "Failed", description: error.message }),
  });
  const rescan = useMutation({
    mutationFn: () => api.rescanTarget(targetId),
    onSuccess: (target) => {
      toast({ title: "Rescan queued", description: `New scan #${target.id}` });
      navigate(`/targets/${target.id}`);
    },
    onError: (error: Error) =>
      toast({ variant: "destructive", title: "Failed", description: error.message }),
  });

  const filteredTasks = useMemo(() => {
    const query = taskSearch.trim().toLowerCase();
    return (tasks.data?.items ?? []).filter(
      (task) =>
        (taskStatus === "all" || task.status === taskStatus) &&
        (!query ||
          `${task.module_name} ${task.capability} ${task.error_code ?? ""}`
            .toLowerCase()
            .includes(query)),
    );
  }, [taskSearch, taskStatus, tasks.data?.items]);
  const filteredEvents = useMemo(() => {
    const query = eventSearch.trim().toLowerCase();
    return eventHistory.filter(
      (event) =>
        (eventLevel === "all" || event.level === eventLevel) &&
        (!query || `${event.event_type} ${event.message}`.toLowerCase().includes(query)),
    );
  }, [eventHistory, eventLevel, eventSearch]);
  const filteredLegacyOutput = useMemo(() => {
    const output = legacyResult.data?.output ?? "";
    if (!legacyFilter) return output;
    return output
      .split(/\r?\n/)
      .filter((line) => line.toLowerCase().includes(legacyFilter.toLowerCase()))
      .join("\n");
  }, [legacyFilter, legacyResult.data?.output]);

  if (detail.isLoading) {
    return <p className="text-sm text-muted-foreground">Loading scan intelligence…</p>;
  }
  if (detail.isError) {
    return <p className="text-sm text-rose-600 dark:text-rose-400">Unable to load this scan: {detail.error.message}</p>;
  }
  if (!detail.data) return <p className="text-sm text-muted-foreground">Scan data is unavailable.</p>;

  const target = detail.data;
  const canCancel = target.status === "queued" || target.status === "running";
  const kinds = Object.keys(summary.data?.assets_by_kind ?? {}).sort();
  const selectAsset = (asset: Asset) => setSelectedAssetId(asset.id);
  const activeLoadError =
    (activeTab === "overview" && (summary.error || assets.error || comparison.error)) ||
    (activeTab === "assets" && assets.error) ||
    (activeTab === "graph" && graph.error) ||
    (activeTab === "tasks" && tasks.error) ||
    (activeTab === "events" && events.error) ||
    (activeTab === "scope" && scope.error) ||
    (activeTab === "legacy" && legacyResult.error);

  return (
    <div className="space-y-6">
      <div className="surface-hero flex flex-wrap items-start justify-between gap-5 rounded-2xl border border-border/70 p-5 sm:p-6">
        <div className="flex min-w-0 items-start gap-3">
          <Button asChild size="icon" variant="ghost">
            <Link to="/targets" aria-label="Back to targets"><ArrowLeft /></Link>
          </Button>
          <div className="min-w-0">
            <div className="mb-2 flex flex-wrap items-center gap-2">
              <Badge variant="outline">scan #{target.id}</Badge>
              <Badge variant="outline">{target.target_kind.replaceAll("_", " ")}</Badge>
              <StatusBadge status={target.status} />
            </div>
            <h1 className="break-all font-mono text-xl font-semibold leading-relaxed sm:text-2xl">
              {target.url}
            </h1>
            <p className="mt-2 text-xs text-muted-foreground">
              Queued {formatRelative(target.created_at)} · Started {formatRelative(target.started_at)} · Completed {formatRelative(target.completed_at)}
            </p>
            {!!target.tags.length && (
              <div className="mt-3 flex flex-wrap gap-1">
                {target.tags.map((tag) => <Badge key={tag} variant="outline">{tag}</Badge>)}
              </div>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <Badge variant="outline" className="capitalize">{target.profile} profile</Badge>
          {canCancel && (
            <Button size="sm" variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending}>
              <Ban /> Cancel
            </Button>
          )}
          <Button
            size="sm"
            variant="outline"
            onClick={() => rescan.mutate()}
            disabled={rescan.isPending || canCancel}
            title={canCancel ? "Wait for completion or cancel first" : "Create an incremental rescan"}
          >
            <RefreshCcw /> Rescan
          </Button>
        </div>
      </div>

      {target.error && (
        <Card className="border-rose-500/30">
          <CardContent className="py-3 text-sm text-rose-400">{target.error}</CardContent>
        </Card>
      )}

      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
        <Metric
          value={summary.data?.assets_total ?? 0}
          label="Canonical assets"
          detail={`${Object.keys(summary.data?.assets_by_kind ?? {}).length} entity types`}
        />
        <Metric
          value={summary.data?.relationships_total ?? 0}
          label="Typed relationships"
          detail={`${Object.keys(summary.data?.relationships_by_type ?? {}).length} relationship types`}
        />
        <Metric
          value={summary.data?.observations_total ?? 0}
          label="Provenance observations"
          detail={`${Object.keys(summary.data?.observations_by_module ?? {}).length} producing modules`}
        />
        <Metric
          value={summary.data?.tasks_total ?? 0}
          label="Result-driven tasks"
          detail={`${summary.data?.tasks_by_status.running ?? 0} running · ${summary.data?.tasks_by_status.failed ?? 0} failed`}
        />
      </div>

      <Tabs value={activeTab} onValueChange={setActiveTab} className="space-y-4">
        <TabsList className="h-auto w-full justify-start overflow-x-auto rounded-xl bg-secondary/45 p-1">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="assets">
            Assets <span className="ml-1 text-[10px] text-muted-foreground">{summary.data?.assets_total ?? 0}</span>
          </TabsTrigger>
          <TabsTrigger value="graph">Graph</TabsTrigger>
          <TabsTrigger value="changes">Changes</TabsTrigger>
          <TabsTrigger value="tasks">
            Tasks <span className="ml-1 text-[10px] text-muted-foreground">{summary.data?.tasks_total ?? 0}</span>
          </TabsTrigger>
          <TabsTrigger value="events">Timeline</TabsTrigger>
          <TabsTrigger value="scope">Scope</TabsTrigger>
          {!!target.results.length && <TabsTrigger value="legacy">Legacy</TabsTrigger>}
        </TabsList>

        {activeLoadError && (
          <Card className="border-rose-500/30">
            <CardContent className="flex flex-wrap items-center justify-between gap-3 py-3 text-sm text-rose-600 dark:text-rose-400">
              <span>Some intelligence could not be loaded: {activeLoadError.message}</span>
              <Button size="sm" variant="outline" onClick={() => void queryClient.invalidateQueries({ queryKey: [activeTab, targetId] })}>Retry</Button>
            </CardContent>
          </Card>
        )}

        <TabsContent value="overview" className="space-y-4">
          {comparison.data && (
            <Card className="border-primary/20">
              <CardContent className="flex flex-wrap items-center gap-x-5 gap-y-2 py-4 text-sm">
                <GitCompareArrows className="h-5 w-5 text-primary" />
                <span>Since scan #{comparison.data.baseline_target_id}</span>
                <span className="text-emerald-400">+{comparison.data.added.length} added</span>
                <span className="text-rose-400">−{comparison.data.removed.length} removed</span>
                <span className="text-amber-400">{comparison.data.changed.length} changed</span>
                <span className="text-muted-foreground">{comparison.data.unchanged_count} unchanged</span>
                {comparison.data.truncated && <Badge variant="outline">bounded comparison</Badge>}
              </CardContent>
            </Card>
          )}
          <div className="grid gap-4 lg:grid-cols-3">
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Boxes className="h-4 w-4 text-cyan-400" /> Attack-surface composition</CardTitle></CardHeader>
              <CardContent><DistributionBars values={summary.data?.assets_by_kind} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><ListTree className="h-4 w-4 text-violet-400" /> Discovery pathways</CardTitle></CardHeader>
              <CardContent><DistributionBars values={summary.data?.relationships_by_type} /></CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2 text-base"><Sparkles className="h-4 w-4 text-amber-400" /> Producing intelligence</CardTitle></CardHeader>
              <CardContent><DistributionBars values={summary.data?.observations_by_module} /></CardContent>
            </Card>
          </div>
          <div className="grid gap-4 lg:grid-cols-[1.15fr_.85fr]">
            <Card>
              <CardHeader><CardTitle className="text-base">Highest-priority discoveries</CardTitle></CardHeader>
              <CardContent>
                <AssetListRows assets={assets.data?.items ?? []} selectedId={selectedAssetId} onSelect={selectAsset} />
              </CardContent>
            </Card>
            <AssetInspector intelligence={assetIntelligence.data} loading={assetIntelligence.isLoading} onSelectRelated={setSelectedAssetId} />
          </div>
        </TabsContent>

        <TabsContent value="assets" className="space-y-4">
          <Card>
            <CardContent className="flex flex-wrap gap-2 p-4">
              <div className="relative min-w-[240px] flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input className="pl-9" value={assetSearch} onChange={(event) => { setAssetSearch(event.target.value); setAssetPage(1); }} placeholder="Search canonical assets" aria-label="Search canonical assets" />
              </div>
              <select aria-label="Filter asset kind" className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={assetKind} onChange={(event) => { setAssetKind(event.target.value); setAssetPage(1); }}>
                <option value="all">All asset kinds</option>
                {kinds.map((kind) => <option key={kind} value={kind}>{kind.replaceAll("_", " ")}</option>)}
              </select>
              <select aria-label="Filter minimum priority" className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={assetPriority} onChange={(event) => { setAssetPriority(event.target.value); setAssetPage(1); }}>
                <option value="0">Any priority</option><option value="25">Priority ≥ 25</option><option value="50">Priority ≥ 50</option><option value="75">Priority ≥ 75</option>
              </select>
              <Badge variant="outline" className="px-3">{assets.data?.total ?? 0} results</Badge>
            </CardContent>
          </Card>
          <div className="grid gap-4 lg:grid-cols-[minmax(320px,.85fr)_minmax(420px,1.15fr)]">
            <AssetListRows assets={assets.data?.items ?? []} selectedId={selectedAssetId} onSelect={selectAsset} />
            <AssetInspector intelligence={assetIntelligence.data} loading={assetIntelligence.isLoading} onSelectRelated={setSelectedAssetId} />
          </div>
          {(assets.data?.total ?? 0) > (assets.data?.page_size ?? 100) && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-xs text-muted-foreground">Page {assets.data?.page ?? assetPage} of {Math.ceil((assets.data?.total ?? 0) / (assets.data?.page_size ?? 100))}</p>
              <div className="flex gap-2">
                <Button size="sm" variant="outline" disabled={assetPage <= 1 || assets.isFetching} onClick={() => setAssetPage((page) => Math.max(page - 1, 1))}>Previous</Button>
                <Button size="sm" variant="outline" disabled={assetPage >= Math.ceil((assets.data?.total ?? 0) / (assets.data?.page_size ?? 100)) || assets.isFetching} onClick={() => setAssetPage((page) => page + 1)}>Next</Button>
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="graph">
          <Card>
            <CardHeader><CardTitle>Interactive attack-surface graph</CardTitle></CardHeader>
            <CardContent><GraphExplorer graph={graph.data} selectedId={selectedAssetId} onSelect={selectAsset} /></CardContent>
          </Card>
          {selectedAssetId && (
            <div className="mt-4">
              <AssetInspector intelligence={assetIntelligence.data} loading={assetIntelligence.isLoading} onSelectRelated={setSelectedAssetId} />
            </div>
          )}
        </TabsContent>

        <TabsContent value="changes">
          {!target.parent_target_id ? (
            <Card><CardContent className="p-10 text-center"><GitCompareArrows className="mx-auto mb-3 h-7 w-7 text-muted-foreground" /><p className="text-sm text-muted-foreground">Run an incremental rescan to compare this knowledge snapshot over time.</p></CardContent></Card>
          ) : (
            <div className="space-y-4">
              {comparison.data?.truncated && <p className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3 text-sm text-amber-700 dark:text-amber-300">This comparison is bounded. Counts shown below are the returned subset, not complete totals.</p>}
              <div className="grid gap-4 lg:grid-cols-3">
              {(["added", "changed", "removed"] as const).map((category) => (
                <Card key={category}>
                  <CardHeader><CardTitle className={category === "added" ? "text-emerald-400" : category === "removed" ? "text-rose-400" : "text-amber-400"}>{category[0].toUpperCase() + category.slice(1)} · {comparison.data?.[category].length ?? 0}</CardTitle></CardHeader>
                  <CardContent className="max-h-[560px] space-y-2 overflow-auto">
                    {comparison.data?.[category].map((asset) => (
                      <button key={asset.id} onClick={() => setSelectedAssetId(asset.id)} className="w-full rounded-lg border border-border/70 p-3 text-left hover:bg-secondary/30"><Badge variant="outline">{asset.kind}</Badge><p className="mt-2 break-all font-mono text-xs">{asset.canonical_value}</p></button>
                    ))}
                    {!comparison.data?.[category].length && <p className="text-sm text-muted-foreground">No {category} assets.</p>}
                  </CardContent>
                </Card>
              ))}
              </div>
            </div>
          )}
        </TabsContent>

        <TabsContent value="tasks">
          <div className="grid gap-4 lg:grid-cols-[390px_1fr]">
            <Card>
              <CardHeader className="space-y-3">
                <CardTitle>Task execution graph</CardTitle>
                <div className="relative"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input className="pl-9" value={taskSearch} onChange={(event) => setTaskSearch(event.target.value)} placeholder="Module, capability, error" /></div>
                <select className="h-9 rounded-md border border-input bg-background px-3 text-sm" value={taskStatus} onChange={(event) => setTaskStatus(event.target.value as typeof taskStatus)}><option value="all">All task states</option>{Object.keys(summary.data?.tasks_by_status ?? {}).sort().map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select>
              </CardHeader>
              <CardContent className="max-h-[68vh] overflow-auto px-2">
                <ul className="space-y-1">
                  {filteredTasks.map((task) => (
                    <li key={task.id}><button onClick={() => setActiveTask(task.id)} className={`w-full rounded-lg px-3 py-2 text-left ${activeTask === task.id ? "bg-primary/10" : "hover:bg-secondary/60"}`}><div className="flex items-center justify-between gap-2"><span className="font-mono text-xs">{task.module_name}</span><StatusBadge status={task.status} /></div><p className="mt-1 text-xs text-muted-foreground">{task.capability} · attempt {task.attempts}/{task.max_attempts}</p><div className="mt-2 flex gap-1"><Badge variant="outline">{task.scope_basis}</Badge>{task.cache_hit_task_id && <Badge variant="outline">cache hit</Badge>}{task.parent_task_id && <Badge variant="outline">from #{task.parent_task_id}</Badge>}</div></button></li>
                  ))}
                </ul>
                {!filteredTasks.length && <p className="p-6 text-center text-sm text-muted-foreground">No tasks match.</p>}
                {(tasks.data?.total ?? 0) > (tasks.data?.page_size ?? 100) && <div className="flex items-center justify-between p-3"><Button size="sm" variant="outline" disabled={taskPage <= 1 || tasks.isFetching} onClick={() => setTaskPage((page) => Math.max(page - 1, 1))}>Previous</Button><span className="text-xs text-muted-foreground">{taskPage}/{Math.ceil((tasks.data?.total ?? 0) / (tasks.data?.page_size ?? 100))}</span><Button size="sm" variant="outline" disabled={taskPage >= Math.ceil((tasks.data?.total ?? 0) / (tasks.data?.page_size ?? 100)) || tasks.isFetching} onClick={() => setTaskPage((page) => page + 1)}>Next</Button></div>}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle className="font-mono text-base">{taskDetail.data?.module_name ?? "Select a task"}</CardTitle></CardHeader>
              <CardContent>
                {taskDetail.data ? (
                  <div className="space-y-4">
                    <div className="grid gap-3 sm:grid-cols-3">
                      <div className="rounded-lg bg-secondary/30 p-3 text-xs"><span className="text-muted-foreground">State</span><div className="mt-1"><StatusBadge status={taskDetail.data.status} /></div></div>
                      <div className="rounded-lg bg-secondary/30 p-3 text-xs"><span className="text-muted-foreground">Scope basis</span><p className="mt-1 font-medium">{taskDetail.data.scope_basis}</p></div>
                      <div className="rounded-lg bg-secondary/30 p-3 text-xs"><span className="text-muted-foreground">Runtime budget</span><p className="mt-1 font-medium">{taskDetail.data.timeout_seconds}s</p></div>
                    </div>
                    {taskDetail.data.error_detail && <p className="rounded-lg border border-rose-500/30 bg-rose-500/5 p-3 text-sm text-rose-400">{taskDetail.data.error_code}: {taskDetail.data.error_detail}</p>}
                    <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Structured summary</h3><pre className="max-h-64 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-secondary/40 p-4 text-xs">{JSON.stringify(taskDetail.data.output_summary, null, 2)}</pre></section>
                    <details><summary className="cursor-pointer text-xs font-semibold uppercase tracking-wider text-muted-foreground">Effective configuration</summary><pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-secondary/40 p-4 text-xs">{JSON.stringify(taskDetail.data.config, null, 2)}</pre></details>
                    {taskDetail.data.raw_output && <section><h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Bounded raw evidence</h3><pre className="max-h-[48vh] overflow-auto whitespace-pre-wrap break-words rounded-lg bg-secondary/40 p-4 text-xs">{taskDetail.data.raw_output}</pre></section>}
                  </div>
                ) : (
                  <p className="py-16 text-center text-sm text-muted-foreground">Select a task to inspect execution, evidence, retry state, cache lineage, and structured output.</p>
                )}
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="events">
          <Card>
            <CardHeader className="flex-row flex-wrap items-center justify-between gap-3">
              <CardTitle>Execution timeline</CardTitle>
              <div className="flex flex-wrap gap-2"><Input className="w-64" value={eventSearch} onChange={(event) => setEventSearch(event.target.value)} placeholder="Search event history" aria-label="Search event history" /><select aria-label="Filter event level" className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={eventLevel} onChange={(event) => setEventLevel(event.target.value)}><option value="all">All levels</option>{[...new Set(eventHistory.map((event) => event.level))].sort().map((level) => <option key={level} value={level}>{level}</option>)}</select></div>
            </CardHeader>
            <CardContent>
              <ol className="relative space-y-1 border-l border-border pl-5">
                {filteredEvents.map((event) => (
                  <li key={event.id} className="relative py-3"><span className={`absolute -left-[25px] top-5 h-2 w-2 rounded-full ${event.level === "error" ? "bg-rose-400" : event.level === "warning" ? "bg-amber-400" : "bg-cyan-400"}`} /><div className="flex flex-wrap items-center gap-2"><Badge variant="outline">{event.event_type}</Badge>{event.task_id && <Badge variant="outline">task #{event.task_id}</Badge>}<span className="text-xs text-muted-foreground">{formatRelative(event.created_at)}</span></div><p className={`mt-2 text-sm ${event.level === "error" ? "text-rose-400" : ""}`}>{event.message}</p>{Object.keys(event.data).length > 0 && <details className="mt-2"><summary className="cursor-pointer text-xs text-muted-foreground">Event data</summary><pre className="mt-2 max-h-40 overflow-auto rounded-lg bg-secondary/40 p-3 text-[11px]">{JSON.stringify(event.data, null, 2)}</pre></details>}</li>
                ))}
              </ol>
              {!filteredEvents.length && <p className="p-8 text-center text-sm text-muted-foreground">No events match.</p>}
              {events.hasNextPage && <div className="mt-3 text-center"><Button size="sm" variant="outline" disabled={events.isFetchingNextPage} onClick={() => void events.fetchNextPage()}>{events.isFetchingNextPage ? "Loading…" : "Load next 500 events"}</Button></div>}
              {eventHistory.length >= 2000 && <p className="mt-3 text-xs text-amber-700 dark:text-amber-300">Timeline view retains the latest 2,000 events. Use the API for complete event export.</p>}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="scope">
          <div className="grid gap-4 lg:grid-cols-[1fr_390px]">
            <Card>
              <CardHeader><CardTitle className="flex items-center gap-2"><ShieldCheck className="h-5 w-5 text-emerald-400" /> Central scope policy</CardTitle></CardHeader>
              <CardContent className="space-y-2">
                {scope.data?.map((rule) => (
                  <div key={rule.id} className="flex items-center justify-between gap-3 rounded-lg border border-border p-3"><div className="min-w-0"><div className="flex flex-wrap gap-2"><Badge variant={rule.action === "exclude" ? "destructive" : "outline"}>{rule.action}</Badge><Badge variant="outline">{rule.rule_type}</Badge>{rule.asset_kind && <Badge variant="outline">{rule.asset_kind}</Badge>}</div><p className="mt-2 break-all font-mono text-xs">{rule.normalized_pattern}</p>{rule.reason && <p className="mt-1 text-xs text-muted-foreground">{rule.reason}</p>}</div><Button size="sm" variant="ghost" disabled={deleteScope.isPending} onClick={() => { if (window.confirm(`Delete this ${rule.action} rule and immediately reconcile unfinished work?`)) deleteScope.mutate(rule.id); }}>Delete</Button></div>
                ))}
              </CardContent>
            </Card>
            <Card>
              <CardHeader><CardTitle>Add and reconcile rule</CardTitle></CardHeader>
              <CardContent className="space-y-3">
                <select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={scopeAction} onChange={(event) => setScopeAction(event.target.value as typeof scopeAction)}><option value="exclude">Exclude</option><option value="include">Include</option></select>
                <select className="h-10 w-full rounded-md border border-input bg-background px-3 text-sm" value={scopeType} onChange={(event) => setScopeType(event.target.value as typeof scopeType)}><option value="exact">Exact host/value</option><option value="subdomain">Domain and subdomains</option><option value="cidr">CIDR range</option><option value="url_prefix">URL prefix</option><option value="regex">Safe regular expression</option></select>
                <Input value={scopePattern} onChange={(event) => setScopePattern(event.target.value)} placeholder="Authorized or excluded pattern" />
                <p className="text-xs leading-relaxed text-muted-foreground">Exclusions always win. A rule change immediately reconciles unfinished and previously observed work. Only add active infrastructure that the authorization explicitly covers.</p>
                <Button className="w-full" disabled={!scopePattern.trim() || addScope.isPending} onClick={() => addScope.mutate()}>Apply and reconcile</Button>
              </CardContent>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="legacy">
          <div className="grid gap-4 lg:grid-cols-[290px_1fr]">
            <Card><CardHeader><CardTitle>Legacy module output</CardTitle></CardHeader><CardContent className="px-2"><ul>{target.results.map((result) => <li key={result.module}><button onClick={() => setActiveLegacyModule(result.module)} className="flex w-full items-center justify-between rounded-md px-3 py-2 hover:bg-secondary/60"><span className="font-mono text-sm">{result.module}</span><StatusBadge status={result.status} /></button></li>)}</ul></CardContent></Card>
            <Card><CardHeader className="flex-row flex-wrap items-center justify-between gap-2"><CardTitle className="font-mono text-base">{activeLegacyModule ?? "Select a module"}</CardTitle>{activeLegacyModule && <div className="flex gap-2"><div className="relative w-52"><Search className="absolute left-2 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input className="h-9 pl-8" value={legacyFilter} onChange={(event) => setLegacyFilter(event.target.value)} placeholder="Filter output" aria-label="Filter legacy output" /></div>{legacyResult.data?.has_output && <Button size="sm" variant="outline" onClick={() => void api.downloadResult(targetId, activeLegacyModule).catch((error: Error) => toast({ variant: "destructive", title: "Download failed", description: error.message }))}><Download /> Download</Button>}</div>}</CardHeader><CardContent><pre className="max-h-[60vh] overflow-auto whitespace-pre-wrap break-words rounded-md bg-secondary/40 p-4 text-xs">{highlight(filteredLegacyOutput || "(empty)", legacyFilter)}</pre></CardContent></Card>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
