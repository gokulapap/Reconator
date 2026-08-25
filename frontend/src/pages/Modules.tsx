import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Boxes, CheckCircle2, Search, Shield, Workflow, XCircle } from "lucide-react";

import { api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";

export function Modules() {
  const modules = useQuery({ queryKey: ["modules"], queryFn: api.modules });
  const [search, setSearch] = useState("");
  const [mode, setMode] = useState("all");
  const [availability, setAvailability] = useState("all");
  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (modules.data ?? []).filter(
      (module) =>
        (mode === "all" || module.mode === mode) &&
        (availability === "all" ||
          (availability === "available" ? module.available : !module.available)) &&
        (!query ||
          `${module.name} ${module.description} ${module.capability} ${module.consumes.join(" ")} ${module.produces.join(" ")}`
            .toLowerCase()
            .includes(query)),
    );
  }, [availability, mode, modules.data, search]);
  const capabilities = new Set((modules.data ?? []).map((module) => module.capability)).size;
  const available = (modules.data ?? []).filter((module) => module.available).length;

  return (
    <div className="space-y-6">
      {modules.isError && <Card className="border-rose-500/30"><CardContent className="py-3 text-sm text-rose-600 dark:text-rose-400">Unable to load the module registry: {modules.error.message}</CardContent></Card>}
      <div className="surface-hero flex flex-wrap items-end justify-between gap-5 rounded-2xl border border-border/70 p-6">
        <div>
          <Badge variant="outline" className="mb-3">Capability registry</Badge>
          <h1 className="text-2xl font-semibold tracking-tight">Recon implementations</h1>
          <p className="mt-2 max-w-2xl text-sm leading-relaxed text-muted-foreground">
            Tool-agnostic capability contracts selected dynamically from normalized discoveries. Availability reflects this deployment, while scope and profile determine execution.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center text-xs">
          <div className="rounded-xl bg-background/60 px-4 py-3"><Boxes className="mx-auto mb-1 h-4 w-4 text-cyan-400" /><strong className="block text-lg">{modules.data?.length ?? 0}</strong><span className="text-muted-foreground">modules</span></div>
          <div className="rounded-xl bg-background/60 px-4 py-3"><Workflow className="mx-auto mb-1 h-4 w-4 text-violet-400" /><strong className="block text-lg">{capabilities}</strong><span className="text-muted-foreground">capabilities</span></div>
          <div className="rounded-xl bg-background/60 px-4 py-3"><CheckCircle2 className="mx-auto mb-1 h-4 w-4 text-emerald-400" /><strong className="block text-lg">{available}</strong><span className="text-muted-foreground">available</span></div>
        </div>
      </div>

      <Card>
        <CardContent className="flex flex-wrap gap-2 p-4">
          <div className="relative min-w-[260px] flex-1"><Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" /><Input className="pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search capability, entity, or implementation" /></div>
          <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={mode} onChange={(event) => setMode(event.target.value)}><option value="all">All interaction modes</option><option value="local">Local</option><option value="passive">Passive</option><option value="active">Active</option></select>
          <select className="h-10 rounded-md border border-input bg-background px-3 text-sm" value={availability} onChange={(event) => setAvailability(event.target.value)}><option value="all">Any availability</option><option value="available">Available</option><option value="unavailable">Unavailable</option></select>
          <Badge variant="outline" className="px-3">{filtered.length} shown</Badge>
        </CardContent>
      </Card>

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {filtered.map((module) => (
          <Card key={module.name} className={module.available ? "transition-colors hover:border-primary/25" : "opacity-70"}>
            <CardHeader className="pb-3">
              <div className="flex items-start justify-between gap-3">
                <div><CardTitle className="break-all font-mono text-sm">{module.name}</CardTitle><p className="mt-1 text-[11px] text-muted-foreground">v{module.version} · {module.implementation}</p></div>
                <Badge variant={module.available ? "outline" : "destructive"}>{module.available ? <CheckCircle2 className="mr-1 h-3 w-3" /> : <XCircle className="mr-1 h-3 w-3" />}{module.available ? "ready" : "offline"}</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <p className="min-h-10 text-sm leading-relaxed text-muted-foreground">{module.description}</p>
              <div className="mt-4 rounded-lg border border-border/70 bg-secondary/20 p-3"><p className="text-[10px] uppercase tracking-wider text-muted-foreground">Capability</p><p className="mt-1 break-all font-mono text-xs">{module.capability}</p></div>
              <div className="mt-4 grid grid-cols-2 gap-3 text-xs">
                <div><p className="text-muted-foreground">Consumes</p><div className="mt-1 flex flex-wrap gap-1">{module.consumes.map((kind) => <Badge key={kind} variant="outline" className="text-[9px]">{kind}</Badge>)}</div></div>
                <div><p className="text-muted-foreground">Produces</p><div className="mt-1 flex flex-wrap gap-1">{module.produces.length ? module.produces.map((kind) => <Badge key={kind} variant="outline" className="text-[9px]">{kind}</Badge>) : <span className="text-muted-foreground">evidence only</span>}</div></div>
              </div>
              <div className="mt-4 flex flex-wrap gap-1.5"><Badge variant="outline" className={module.mode === "active" ? "border-amber-500/30 text-amber-400" : module.mode === "passive" ? "border-cyan-500/30 text-cyan-400" : ""}><Shield className="mr-1 h-3 w-3" /> {module.mode}</Badge><Badge variant="outline">{module.timeout}s</Badge><Badge variant="outline">cache {Math.round(module.cache_ttl_seconds / 3600)}h</Badge><Badge variant="outline">{module.accepts_derived_inputs ? "derived-safe" : "direct scope"}</Badge></div>
              <p className="mt-3 text-[11px] text-muted-foreground">Profiles: {module.default_profiles.join(" · ")}</p>
              {!!module.depends_on_capabilities.length && <p className="mt-2 text-[11px] text-muted-foreground">Requires: {module.depends_on_capabilities.join(" · ")}</p>}
            </CardContent>
          </Card>
        ))}
      </div>
      {!filtered.length && <Card><CardContent className="p-10 text-center text-sm text-muted-foreground">No capability implementations match these filters.</CardContent></Card>}
    </div>
  );
}
