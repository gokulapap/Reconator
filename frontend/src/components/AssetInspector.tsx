import { ArrowDownLeft, ArrowUpRight, Clock3, Database, GitBranch, ShieldCheck } from "lucide-react";

import type { AssetIntelligence } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatRelative } from "@/lib/utils";

function JsonBlock({ value }: { value: Record<string, unknown> }) {
  if (!Object.keys(value).length) return <span className="text-muted-foreground">None</span>;
  return <pre className="max-h-48 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-secondary/40 p-3 text-[11px]">{JSON.stringify(value, null, 2)}</pre>;
}

export function AssetInspector({
  intelligence,
  loading,
  onSelectRelated,
}: {
  intelligence: AssetIntelligence | undefined;
  loading: boolean;
  onSelectRelated: (assetId: number) => void;
}) {
  if (loading) return <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Loading intelligence…</CardContent></Card>;
  if (!intelligence) return <Card><CardContent className="p-8 text-center text-sm text-muted-foreground">Select an asset to inspect provenance, evidence, attributes, and graph pivots.</CardContent></Card>;
  const { asset, observations, relationships } = intelligence;
  return (
    <Card className="overflow-hidden border-primary/20">
      <CardHeader className="border-b border-border/70 bg-secondary/20">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Badge variant="outline">{asset.kind}</Badge>
          <span className="text-xs text-muted-foreground">priority {asset.priority_score.toFixed(0)}</span>
        </div>
        <CardTitle className="break-all font-mono text-base leading-relaxed">{asset.canonical_value}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5 p-5">
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div className="rounded-lg bg-secondary/30 p-3"><Clock3 className="mb-2 h-4 w-4 text-cyan-400" /><span className="block text-muted-foreground">First seen</span>{formatRelative(asset.first_seen_at)}</div>
          <div className="rounded-lg bg-secondary/30 p-3"><Database className="mb-2 h-4 w-4 text-violet-400" /><span className="block text-muted-foreground">Observations</span>{observations.reduce((total, item) => total + item.observation_count, 0)}</div>
        </div>

        <section>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">Canonical attributes</h3>
          <JsonBlock value={asset.attributes} />
        </section>

        <section>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground"><ShieldCheck className="h-4 w-4" /> Evidence & provenance</h3>
          <div className="space-y-2">
            {observations.map((observation) => (
              <details key={observation.id} className="rounded-lg border border-border/70 p-3">
                <summary className="cursor-pointer list-none">
                  <div className="flex items-center justify-between gap-3">
                    <div><span className="font-mono text-xs">{observation.source_module}</span>{observation.source_name && <span className="ml-2 text-xs text-muted-foreground">via {observation.source_name}</span>}</div>
                    <Badge variant="outline">{Math.round(observation.confidence * 100)}%</Badge>
                  </div>
                  <p className="mt-1 text-[11px] text-muted-foreground">Seen {observation.observation_count}× · {formatRelative(observation.last_observed_at)}{observation.task_id ? ` · task #${observation.task_id}` : ""}</p>
                </summary>
                <div className="mt-3"><JsonBlock value={observation.evidence} /></div>
              </details>
            ))}
            {!observations.length && <p className="text-sm text-muted-foreground">No observations returned.</p>}
            {intelligence.observations_truncated && <p className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-700 dark:text-amber-300">Only the newest provenance observations are shown.</p>}
          </div>
        </section>

        <section>
          <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground"><GitBranch className="h-4 w-4" /> Related intelligence</h3>
          <div className="space-y-2">
            {relationships.map((item) => (
              <button key={item.relationship.id} onClick={() => onSelectRelated(item.related_asset.id)} className="flex w-full items-start gap-3 rounded-lg border border-border/70 p-3 text-left hover:border-primary/40 hover:bg-secondary/30">
                {item.direction === "outgoing" ? <ArrowUpRight className="mt-0.5 h-4 w-4 text-cyan-400" /> : <ArrowDownLeft className="mt-0.5 h-4 w-4 text-violet-400" />}
                <span className="min-w-0 flex-1"><span className="block text-xs text-muted-foreground">{item.direction} · {item.relationship.relationship_type.replaceAll("_", " ")}</span><span className="block break-all font-mono text-xs">{item.related_asset.canonical_value}</span></span>
                <Badge variant="outline">{item.related_asset.kind}</Badge>
              </button>
            ))}
            {!relationships.length && <p className="text-sm text-muted-foreground">No observed relationships for this asset.</p>}
            {intelligence.relationships_truncated && <p className="rounded-md border border-amber-500/30 bg-amber-500/5 p-2 text-xs text-amber-700 dark:text-amber-300">Only a bounded relationship neighborhood is shown.</p>}
          </div>
        </section>
      </CardContent>
    </Card>
  );
}
