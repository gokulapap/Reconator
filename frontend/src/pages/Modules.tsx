import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

export function Modules() {
  const modules = useQuery({ queryKey: ["modules"], queryFn: api.modules });

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Modules</h1>
        <p className="text-sm text-muted-foreground">
          Capability implementations selected dynamically from normalized discoveries.
        </p>
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {modules.data?.map((m) => (
          <Card key={m.name}>
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-2">
                <CardTitle className="font-mono text-sm">{m.name}</CardTitle>
                <Badge variant="outline">{m.mode}</Badge>
              </div>
            </CardHeader>
            <CardContent>
              <p className="text-sm text-muted-foreground">{m.description}</p>
              <dl className="mt-3 grid grid-cols-[auto_1fr] gap-x-2 gap-y-1 text-xs text-muted-foreground">
                <dt>Capability</dt><dd className="font-mono">{m.capability}</dd>
                <dt>Consumes</dt><dd>{m.consumes.join(", ")}</dd>
                <dt>Produces</dt><dd>{m.produces.join(", ") || "evidence only"}</dd>
                <dt>Runtime</dt><dd>{m.implementation} · {m.timeout}s timeout</dd>
                <dt>Cache</dt><dd>{Math.round(m.cache_ttl_seconds / 3600)}h</dd>
                <dt>Profiles</dt><dd>{m.default_profiles.join(", ")}</dd>
                <dt>Scope</dt><dd>{m.accepts_derived_inputs ? "direct + derived-safe" : "direct only"}</dd>
              </dl>
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}
