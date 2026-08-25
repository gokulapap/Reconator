import { useMemo, useState } from "react";
import { List, Orbit, Search } from "lucide-react";

import type { Asset, AssetGraph } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const palette = ["#22d3ee", "#a78bfa", "#34d399", "#fbbf24", "#f472b6", "#60a5fa", "#fb7185"];

function colorFor(kind: string) {
  let hash = 0;
  for (const character of kind) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return palette[hash % palette.length];
}

function compact(value: string, maximum = 28) {
  return value.length > maximum ? `${value.slice(0, maximum - 1)}…` : value;
}

export function GraphExplorer({
  graph,
  selectedId,
  onSelect,
}: {
  graph: AssetGraph | undefined;
  selectedId: number | null;
  onSelect: (asset: Asset) => void;
}) {
  const [mode, setMode] = useState<"map" | "list">("map");
  const [search, setSearch] = useState("");
  const [kind, setKind] = useState("all");
  const [relationshipType, setRelationshipType] = useState("all");

  const nodeMap = useMemo(
    () => new Map((graph?.nodes ?? []).map((node) => [node.id, node])),
    [graph?.nodes],
  );
  const kinds = useMemo(
    () => [...new Set((graph?.nodes ?? []).map((node) => node.kind))].sort(),
    [graph?.nodes],
  );
  const relationshipTypes = useMemo(
    () => [...new Set((graph?.edges ?? []).map((edge) => edge.relationship_type))].sort(),
    [graph?.edges],
  );
  const filteredNodes = useMemo(() => {
    const query = search.trim().toLowerCase();
    return (graph?.nodes ?? []).filter(
      (node) =>
        (kind === "all" || node.kind === kind) &&
        (!query ||
          node.canonical_value.toLowerCase().includes(query) ||
          node.kind.toLowerCase().includes(query)),
    );
  }, [graph?.nodes, kind, search]);
  const visibleNodeIds = useMemo(
    () => new Set(filteredNodes.map((node) => node.id)),
    [filteredNodes],
  );
  const filteredEdges = useMemo(
    () =>
      (graph?.edges ?? []).filter(
        (edge) =>
          visibleNodeIds.has(edge.source_asset_id) &&
          visibleNodeIds.has(edge.target_asset_id) &&
          (relationshipType === "all" || edge.relationship_type === relationshipType),
      ),
    [graph?.edges, relationshipType, visibleNodeIds],
  );
  const mapNodes = filteredNodes.slice(0, 120);
  const mapIds = new Set(mapNodes.map((node) => node.id));
  const positions = useMemo(() => {
    const result = new Map<number, { x: number; y: number }>();
    const grouped = new Map<string, Asset[]>();
    for (const node of mapNodes) {
      grouped.set(node.kind, [...(grouped.get(node.kind) ?? []), node]);
    }
    const groups = [...grouped.entries()];
    groups.forEach(([groupKind, nodes], groupIndex) => {
      const groupAngle = (Math.PI * 2 * groupIndex) / Math.max(groups.length, 1) - Math.PI / 2;
      const centerRadius = groups.length === 1 ? 0 : 155;
      const centerX = 450 + Math.cos(groupAngle) * centerRadius;
      const centerY = 235 + Math.sin(groupAngle) * Math.min(centerRadius, 120);
      nodes.forEach((node, nodeIndex) => {
        const angle = (Math.PI * 2 * nodeIndex) / Math.max(nodes.length, 1) + groupIndex * 0.37;
        const radius = nodes.length === 1 ? 0 : 25 + 12 * Math.sqrt(nodeIndex);
        result.set(node.id, {
          x: centerX + Math.cos(angle) * Math.min(radius, 105),
          y: centerY + Math.sin(angle) * Math.min(radius, 78),
        });
      });
      void groupKind;
    });
    return result;
  }, [mapNodes]);

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[220px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            className="pl-9"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Find an asset in the graph"
          />
        </div>
        <select
          className="h-10 rounded-md border border-input bg-background px-3 text-sm"
          value={kind}
          onChange={(event) => setKind(event.target.value)}
          aria-label="Filter graph by asset kind"
        >
          <option value="all">All asset kinds</option>
          {kinds.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
        </select>
        <select
          className="h-10 rounded-md border border-input bg-background px-3 text-sm"
          value={relationshipType}
          onChange={(event) => setRelationshipType(event.target.value)}
          aria-label="Filter graph by relationship"
        >
          <option value="all">All relationships</option>
          {relationshipTypes.map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}
        </select>
        <div className="flex rounded-md border border-input p-1">
          <Button size="sm" variant={mode === "map" ? "secondary" : "ghost"} onClick={() => setMode("map")}><Orbit /> Map</Button>
          <Button size="sm" variant={mode === "list" ? "secondary" : "ghost"} onClick={() => setMode("list")}><List /> List</Button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {kinds.map((value) => (
          <button key={value} onClick={() => setKind(kind === value ? "all" : value)} className="inline-flex items-center gap-1.5 rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground hover:bg-secondary">
            <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colorFor(value) }} />
            {value.replaceAll("_", " ")}
          </button>
        ))}
      </div>

      {mode === "map" ? (
        <div className="graph-grid overflow-hidden rounded-xl border border-border/70 bg-background/60">
          <svg viewBox="0 0 900 470" className="h-auto min-h-[440px] w-full" role="group" aria-label="Interactive reconnaissance relationship graph">
            <g opacity="0.28">
              {filteredEdges.filter((edge) => mapIds.has(edge.source_asset_id) && mapIds.has(edge.target_asset_id)).slice(0, 500).map((edge) => {
                const source = positions.get(edge.source_asset_id);
                const target = positions.get(edge.target_asset_id);
                if (!source || !target) return null;
                const active = edge.source_asset_id === selectedId || edge.target_asset_id === selectedId;
                return <line key={edge.id} x1={source.x} y1={source.y} x2={target.x} y2={target.y} stroke={active ? "#22d3ee" : "currentColor"} strokeWidth={active ? 2 : 0.8} opacity={active ? 1 : Math.max(edge.confidence, 0.2)} />;
              })}
            </g>
            {mapNodes.map((node) => {
              const position = positions.get(node.id);
              if (!position) return null;
              const selected = selectedId === node.id;
              return (
                <g
                  key={node.id}
                  transform={`translate(${position.x} ${position.y})`}
                  onClick={() => onSelect(node)}
                  onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onSelect(node); } }}
                  role="button"
                  aria-label={`${node.kind}: ${node.canonical_value}`}
                  tabIndex={0}
                  className="cursor-pointer outline-none"
                >
                  {selected && <circle r="16" fill={colorFor(node.kind)} opacity="0.16" />}
                  <circle r={selected ? 8 : 5.5} fill={colorFor(node.kind)} stroke="hsl(var(--background))" strokeWidth="2" />
                  {(selected || mapNodes.length <= 35) && (
                    <text x="11" y="4" className="select-none fill-foreground text-[9px] font-medium">{compact(node.canonical_value)}</text>
                  )}
                  <title>{`${node.kind}: ${node.canonical_value}`}</title>
                </g>
              );
            })}
          </svg>
          <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border/70 px-4 py-2 text-xs text-muted-foreground">
            <span>{filteredNodes.length.toLocaleString()} nodes · {filteredEdges.length.toLocaleString()} edges</span>
            {filteredNodes.length > mapNodes.length && <span>Map shows the first {mapNodes.length} filtered nodes</span>}
          </div>
        </div>
      ) : (
        <div className="max-h-[560px] overflow-auto rounded-xl border border-border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-card"><tr className="border-b text-left text-xs text-muted-foreground"><th className="p-3">Source</th><th>Relationship</th><th>Target</th><th className="pr-3">Confidence</th></tr></thead>
            <tbody>
              {filteredEdges.map((edge) => {
                const source = nodeMap.get(edge.source_asset_id);
                const target = nodeMap.get(edge.target_asset_id);
                return (
                  <tr key={edge.id} className="border-b border-border/50 hover:bg-secondary/30">
                    <td className="max-w-[320px] p-3"><button className="text-left font-mono text-xs break-all hover:text-primary" onClick={() => source && onSelect(source)}>{source?.canonical_value ?? `#${edge.source_asset_id}`}</button></td>
                    <td><Badge variant="outline">{edge.relationship_type}</Badge></td>
                    <td className="max-w-[320px]"><button className="text-left font-mono text-xs break-all hover:text-primary" onClick={() => target && onSelect(target)}>{target?.canonical_value ?? `#${edge.target_asset_id}`}</button></td>
                    <td className="pr-3 tabular-nums">{Math.round(edge.confidence * 100)}%</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {!filteredEdges.length && <p className="p-8 text-center text-sm text-muted-foreground">No relationships match these filters.</p>}
        </div>
      )}

      {graph?.truncated && <p className="text-xs text-amber-700 dark:text-amber-300">This is a bounded operational graph. Use the paginated API for complete analysis.</p>}
    </div>
  );
}
