import { cn } from "@/lib/utils";

const tones = [
  "bg-cyan-400",
  "bg-violet-400",
  "bg-emerald-400",
  "bg-amber-400",
  "bg-fuchsia-400",
  "bg-sky-400",
  "bg-rose-400",
];

export function DistributionBars({
  values,
  limit = 8,
  empty = "No data yet",
}: {
  values: Record<string, number> | undefined;
  limit?: number;
  empty?: string;
}) {
  const rows = Object.entries(values ?? {})
    .sort((left, right) => right[1] - left[1] || left[0].localeCompare(right[0]))
    .slice(0, limit);
  const maximum = Math.max(...rows.map(([, value]) => value), 1);

  if (!rows.length) {
    return <p className="py-6 text-center text-sm text-muted-foreground">{empty}</p>;
  }

  return (
    <div className="space-y-3">
      {rows.map(([label, value], index) => (
        <div key={label}>
          <div className="mb-1 flex items-center justify-between gap-3 text-xs">
            <span className="truncate font-mono text-muted-foreground">
              {label.replaceAll("_", " ")}
            </span>
            <span className="font-semibold tabular-nums">{value.toLocaleString()}</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-secondary">
            <div
              className={cn("h-full rounded-full transition-all", tones[index % tones.length])}
              style={{ width: `${Math.max((value / maximum) * 100, 2)}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}
