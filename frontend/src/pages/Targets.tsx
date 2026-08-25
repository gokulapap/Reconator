import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { Download, Plus, Search, Tag, Trash2, Upload } from "lucide-react";

import { api, type TargetKind, type TargetStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { StatusBadge } from "@/components/StatusBadge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { useToast } from "@/hooks/use-toast";
import { formatRelative } from "@/lib/utils";

const tabs: { id: "all" | TargetStatus; label: string }[] = [
  { id: "all", label: "All" },
  { id: "queued", label: "Queued" },
  { id: "running", label: "Running" },
  { id: "completed", label: "Completed" },
  { id: "failed", label: "Failed" },
  { id: "cancelled", label: "Cancelled" },
];

export function Targets() {
  const qc = useQueryClient();
  const { toast } = useToast();
  const [tab, setTab] = useState<"all" | TargetStatus>("all");
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");

  const [singleOpen, setSingleOpen] = useState(false);
  const [singleUrl, setSingleUrl] = useState("");
  const [singleKind, setSingleKind] = useState<TargetKind>("domain");
  const [singleTags, setSingleTags] = useState("");
  const [singleProfile, setSingleProfile] = useState<"passive" | "balanced" | "active">("balanced");
  const [singleAuthorized, setSingleAuthorized] = useState(false);
  const [singleModules, setSingleModules] = useState<string[]>([]);

  const [bulkOpen, setBulkOpen] = useState(false);
  const [bulkText, setBulkText] = useState("");
  const [bulkKind, setBulkKind] = useState<TargetKind>("domain");
  const [bulkTags, setBulkTags] = useState("");
  const [bulkProfile, setBulkProfile] = useState<"passive" | "balanced" | "active">("balanced");
  const [bulkAuthorized, setBulkAuthorized] = useState(false);
  const [bulkModules, setBulkModules] = useState<string[]>([]);

  const modules = useQuery({ queryKey: ["modules"], queryFn: api.modules });

  const targets = useQuery({
    queryKey: ["targets", tab, search, tag],
    queryFn: () =>
      api.listTargets({
        status: tab === "all" ? undefined : tab,
        search: search || undefined,
        tag: tag || undefined,
        page_size: 100,
      }),
    refetchInterval: 5000,
  });

  const create = useMutation({
    mutationFn: (payload: {
      url: string;
      target_kind: TargetKind;
      tags?: string[];
      profile: "passive" | "balanced" | "active";
      selected_modules?: string[] | null;
      authorization_confirmed: boolean;
    }) =>
      api.createTarget(payload),
    onSuccess: (t) => {
      toast({ title: "Queued", description: t.url });
      setSingleOpen(false);
      setSingleUrl("");
      setSingleTags("");
      setSingleAuthorized(false);
      setSingleModules([]);
      qc.invalidateQueries();
    },
    onError: (e: Error) =>
      toast({ variant: "destructive", title: "Failed", description: e.message }),
  });

  const bulk = useMutation({
    mutationFn: (payload: {
      urls: string[];
      target_kind: TargetKind;
      tags?: string[];
      profile: "passive" | "balanced" | "active";
      selected_modules?: string[] | null;
      authorization_confirmed: boolean;
    }) =>
      api.bulkCreate(payload),
    onSuccess: (r) => {
      toast({
        title: `Queued ${r.created.length} targets`,
        description:
          r.conflicts.length || Object.keys(r.errors).length
            ? `${r.conflicts.length} conflicts · ${Object.keys(r.errors).length} errors`
            : undefined,
      });
      setBulkOpen(false);
      setBulkText("");
      setBulkTags("");
      setBulkAuthorized(false);
      setBulkModules([]);
      qc.invalidateQueries();
    },
    onError: (e: Error) =>
      toast({ variant: "destructive", title: "Failed", description: e.message }),
  });

  const remove = useMutation({
    mutationFn: (id: number) => api.deleteTarget(id),
    onSuccess: () => qc.invalidateQueries(),
    onError: (e: Error) =>
      toast({ variant: "destructive", title: "Failed", description: e.message }),
  });

  const cancel = useMutation({
    mutationFn: (id: number) => api.cancelTarget(id),
    onSuccess: () => qc.invalidateQueries(),
    onError: (e: Error) =>
      toast({ variant: "destructive", title: "Cancel failed", description: e.message }),
  });

  const parseTags = (s: string) =>
    s
      .split(/[, \t]+/)
      .map((x) => x.trim())
      .filter(Boolean);

  const submitBulk = () => {
    const urls = bulkText
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter(Boolean);
    if (!urls.length) return;
    bulk.mutate({
      urls,
      target_kind: bulkKind,
      tags: parseTags(bulkTags),
      profile: bulkProfile,
      selected_modules: bulkModules.length ? bulkModules : null,
      authorization_confirmed: bulkAuthorized,
    });
  };

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Targets</h1>
          <p className="text-sm text-muted-foreground">
            Add authorized domains, URLs, IP addresses, or CIDRs to queue recon.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => void api.exportTargets("csv")}>
            <Download /> CSV
          </Button>
          <Button variant="outline" size="sm" onClick={() => void api.exportTargets("json")}>
            <Download /> JSON
          </Button>

          <Dialog open={bulkOpen} onOpenChange={setBulkOpen}>
            <DialogTrigger asChild>
              <Button variant="outline">
                <Upload /> Bulk add
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Bulk add targets</DialogTitle>
                <DialogDescription>
                  One target per line. Up to 500 targets of the selected type.
                </DialogDescription>
              </DialogHeader>
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={bulkKind}
                onChange={(event) => setBulkKind(event.target.value as TargetKind)}
              >
                <option value="domain">Domain</option>
                <option value="url">HTTP(S) URL</option>
                <option value="ip_address">IP address</option>
                <option value="cidr">CIDR range</option>
              </select>
              <ModulePicker
                modules={modules.data ?? []}
                selected={bulkModules}
                onChange={setBulkModules}
              />
              <Textarea
                rows={10}
                placeholder={"example.com\nfoo.bar\nacme.io"}
                value={bulkText}
                onChange={(e) => setBulkText(e.target.value)}
                className="font-mono text-xs"
              />
              <Input
                placeholder="tags (comma-separated, optional)"
                value={bulkTags}
                onChange={(e) => setBulkTags(e.target.value)}
              />
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={bulkProfile}
                onChange={(event) => setBulkProfile(event.target.value as typeof bulkProfile)}
              >
                <option value="passive">Passive — public data and local analysis</option>
                <option value="balanced">Balanced — safe active discovery</option>
                <option value="active">Active — explicitly selected active modules</option>
              </select>
              <ModulePicker
                modules={modules.data ?? []}
                selected={singleModules}
                onChange={setSingleModules}
              />
              <label className="flex items-start gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={bulkAuthorized}
                  onChange={(event) => setBulkAuthorized(event.target.checked)}
                />
                I confirm I am authorized to assess every target in this list.
              </label>
              <DialogFooter>
                <Button
                  disabled={!bulkText.trim() || !bulkAuthorized || bulk.isPending}
                  onClick={submitBulk}
                >
                  Queue {bulkText.split(/\r?\n/).filter((s) => s.trim()).length}{" "}
                  targets
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>

          <Dialog open={singleOpen} onOpenChange={setSingleOpen}>
            <DialogTrigger asChild>
              <Button>
                <Plus /> Add target
              </Button>
            </DialogTrigger>
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Add a target</DialogTitle>
                <DialogDescription>
                  Choose a target type and provide a value within your authorized scope.
                </DialogDescription>
              </DialogHeader>
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={singleKind}
                onChange={(event) => setSingleKind(event.target.value as TargetKind)}
              >
                <option value="domain">Domain</option>
                <option value="url">HTTP(S) URL</option>
                <option value="ip_address">IP address</option>
                <option value="cidr">CIDR range</option>
              </select>
              <Input
                placeholder={singleKind === "url" ? "https://example.com/app" : singleKind === "ip_address" ? "203.0.113.10" : singleKind === "cidr" ? "203.0.113.0/24" : "example.com"}
                value={singleUrl}
                onChange={(e) => setSingleUrl(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && singleUrl.trim() && singleAuthorized) {
                    create.mutate({
                      url: singleUrl.trim(),
                      target_kind: singleKind,
                      tags: parseTags(singleTags),
                      profile: singleProfile,
                      selected_modules: singleModules.length ? singleModules : null,
                      authorization_confirmed: singleAuthorized,
                    });
                  }
                }}
              />
              <Input
                placeholder="tags (comma-separated, optional)"
                value={singleTags}
                onChange={(e) => setSingleTags(e.target.value)}
              />
              <select
                className="h-10 rounded-md border border-input bg-background px-3 text-sm"
                value={singleProfile}
                onChange={(event) => setSingleProfile(event.target.value as typeof singleProfile)}
              >
                <option value="passive">Passive — public data and local analysis</option>
                <option value="balanced">Balanced — safe active discovery</option>
                <option value="active">Active — explicitly selected active modules</option>
              </select>
              <label className="flex items-start gap-2 text-sm text-muted-foreground">
                <input
                  type="checkbox"
                  className="mt-1"
                  checked={singleAuthorized}
                  onChange={(event) => setSingleAuthorized(event.target.checked)}
                />
                I confirm I own this target or have permission to assess it.
              </label>
              <DialogFooter>
                <Button
                  disabled={!singleUrl.trim() || !singleAuthorized || create.isPending}
                  onClick={() =>
                    create.mutate({
                      url: singleUrl.trim(),
                      target_kind: singleKind,
                      tags: parseTags(singleTags),
                      profile: singleProfile,
                      selected_modules: singleModules.length ? singleModules : null,
                      authorization_confirmed: singleAuthorized,
                    })
                  }
                >
                  Queue scan
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        </div>
      </div>

      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0 flex-wrap">
          <Tabs value={tab} onValueChange={(v) => setTab(v as any)}>
            <TabsList>
              {tabs.map((t) => (
                <TabsTrigger key={t.id} value={t.id}>
                  {t.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
          <div className="flex items-center gap-2">
            <div className="relative w-56">
              <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder="Search domains"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="relative w-44">
              <Tag className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input
                className="pl-8"
                placeholder="Filter by tag"
                value={tag}
                onChange={(e) => setTag(e.target.value)}
              />
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {targets.isLoading ? (
            <p className="text-sm text-muted-foreground">Loading…</p>
          ) : !targets.data?.items.length ? (
            <p className="text-sm text-muted-foreground">No targets match.</p>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Target</TableHead>
                  <TableHead>Tags</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Queued</TableHead>
                  <TableHead>Completed</TableHead>
                  <TableHead className="w-24"></TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {targets.data.items.map((t) => (
                  <TableRow key={t.id}>
                    <TableCell>
                      <Link
                        to={`/targets/${t.id}`}
                        className="font-mono text-sm hover:text-primary"
                      >
                        {t.url}
                      </Link>
                      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{t.target_kind.replace("_", " ")}</p>
                      {t.error && (
                        <p className="text-xs text-rose-400 mt-0.5">{t.error}</p>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex flex-wrap gap-1">
                        {(t.tags || []).map((tg) => (
                          <Badge key={tg} variant="outline">
                            {tg}
                          </Badge>
                        ))}
                      </div>
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={t.status} />
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatRelative(t.created_at)}
                    </TableCell>
                    <TableCell className="text-sm text-muted-foreground">
                      {formatRelative(t.completed_at)}
                    </TableCell>
                    <TableCell className="text-right">
                      {t.status === "running" || t.status === "queued" ? (
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => cancel.mutate(t.id)}
                          title="Cancel"
                        >
                          Cancel
                        </Button>
                      ) : (
                        <Button
                          size="icon"
                          variant="ghost"
                          title="Delete"
                          onClick={() => remove.mutate(t.id)}
                        >
                          <Trash2 className="text-rose-400" />
                        </Button>
                      )}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function ModulePicker({
  modules,
  selected,
  onChange,
}: {
  modules: Awaited<ReturnType<typeof api.modules>>;
  selected: string[];
  onChange: (value: string[]) => void;
}) {
  return (
    <details className="rounded-md border border-input p-3 text-sm">
      <summary className="cursor-pointer text-muted-foreground">
        Module override ({selected.length ? `${selected.length} selected` : "use profile defaults"})
      </summary>
      <div className="mt-3 max-h-48 space-y-2 overflow-auto">
        {modules.map((module) => (
          <label key={module.name} className="flex items-start gap-2">
            <input
              type="checkbox"
              className="mt-1"
              checked={selected.includes(module.name)}
              onChange={(event) =>
                onChange(
                  event.target.checked
                    ? [...selected, module.name].sort()
                    : selected.filter((name) => name !== module.name),
                )
              }
            />
            <span>
              <span className="font-mono text-xs">{module.name}</span>
              <span className="block text-xs text-muted-foreground">{module.description}</span>
            </span>
          </label>
        ))}
      </div>
    </details>
  );
}
