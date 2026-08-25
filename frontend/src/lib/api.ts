const BASE = import.meta.env.VITE_API_URL || "";
const PREFIX = "/api/v1";

const API_KEY_STORAGE = "reconator.apiKey";

export const apiKeyStore = {
  get(): string | null {
    try {
      return localStorage.getItem(API_KEY_STORAGE);
    } catch {
      return null;
    }
  },
  set(value: string) {
    try {
      if (value) localStorage.setItem(API_KEY_STORAGE, value);
      else localStorage.removeItem(API_KEY_STORAGE);
    } catch {
      // Ignore unavailable browser storage.
    }
    window.dispatchEvent(new Event("reconator-api-key-change"));
  },
  clear() {
    try {
      localStorage.removeItem(API_KEY_STORAGE);
    } catch {
      // Ignore unavailable browser storage.
    }
    window.dispatchEvent(new Event("reconator-api-key-change"));
  },
};

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...((init?.headers as Record<string, string>) ?? {}),
  };
  const key = apiKeyStore.get();
  if (key) headers["X-API-Key"] = key;

  const res = await fetch(`${BASE}${PREFIX}${path}`, { ...init, headers });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") {
        detail = body.detail;
      } else if (Array.isArray(body.detail)) {
        detail = body.detail
          .map((item: unknown) => {
            if (!item || typeof item !== "object") return String(item);
            const issue = item as { loc?: unknown[]; msg?: string };
            const location = issue.loc?.slice(1).join(".");
            return `${location ? `${location}: ` : ""}${issue.msg ?? "invalid value"}`;
          })
          .join("; ");
      }
    } catch {
      // Preserve the status fallback for a non-JSON error response.
    }
    throw new Error(detail);
  }
  if (res.status === 204) return undefined as T;
  return res.json();
}

async function download(path: string, fallbackName: string): Promise<void> {
  const headers: Record<string, string> = {};
  const key = apiKeyStore.get();
  if (key) headers["X-API-Key"] = key;
  const res = await fetch(`${BASE}${PREFIX}${path}`, { headers });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      // Preserve the status fallback for a non-JSON error response.
    }
    throw new Error(detail);
  }
  const disposition = res.headers.get("Content-Disposition") ?? "";
  const match = disposition.match(/filename="?([^";]+)"?/i);
  const filename = (match?.[1] || fallbackName).replace(/[\\/\0]/g, "-");
  const href = URL.createObjectURL(await res.blob());
  const anchor = document.createElement("a");
  anchor.href = href;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(href);
}

export type TargetStatus =
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled";

export type TargetKind = "domain" | "url" | "ip_address" | "cidr";

export type ModuleStatus =
  | "pending"
  | "running"
  | "completed"
  | "failed"
  | "skipped";

export type ReconTaskStatus =
  | "queued"
  | "running"
  | "retry_wait"
  | "blocked"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled";

export interface Target {
  id: number;
  url: string;
  target_kind: TargetKind;
  status: TargetStatus;
  error: string | null;
  tags: string[];
  selected_modules: string[] | null;
  profile: "passive" | "balanced" | "active";
  authorization_confirmed: boolean;
  parent_target_id: number | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
}

export interface ScanResultSummary {
  module: string;
  status: ModuleStatus;
  completed_at: string | null;
  has_output: boolean;
}

export interface ScanResult extends ScanResultSummary {
  id: number;
  output: string | null;
  error: string | null;
  started_at: string | null;
}

export interface TargetDetail extends Target {
  notes: string | null;
  results: ScanResultSummary[];
}

export interface TargetList {
  items: Target[];
  total: number;
  page: number;
  page_size: number;
}

export interface Stats {
  queued: number;
  running: number;
  completed: number;
  failed: number;
  cancelled: number;
  total: number;
  avg_duration_seconds: number | null;
}

export interface ModuleInfo {
  name: string;
  version: string;
  description: string;
  timeout: number;
  capability: string;
  consumes: string[];
  produces: string[];
  mode: "local" | "passive" | "active";
  implementation: string;
  default_profiles: string[];
  cache_ttl_seconds: number;
  accepts_derived_inputs: boolean;
  depends_on_capabilities: string[];
  available: boolean;
}

export interface Asset {
  id: number;
  kind: string;
  value: string;
  canonical_value: string;
  attributes: Record<string, unknown>;
  priority_score: number;
  first_seen_at: string;
  last_seen_at: string;
  last_changed_at: string;
  active: boolean;
}

export interface AssetList {
  items: Asset[];
  total: number;
  page: number;
  page_size: number;
}

export interface AssetRelationship {
  id: number;
  source_asset_id: number;
  target_asset_id: number;
  relationship_type: string;
  attributes: Record<string, unknown>;
  confidence: number;
  first_seen_at: string;
  last_seen_at: string;
}

export interface AssetGraph {
  nodes: Asset[];
  edges: AssetRelationship[];
  truncated: boolean;
}

export interface AssetObservation {
  id: number;
  target_id: number;
  asset_id: number;
  task_id: number | null;
  source_module: string;
  source_name: string | null;
  confidence: number;
  evidence: Record<string, unknown>;
  snapshot: Record<string, unknown>;
  first_observed_at: string;
  last_observed_at: string;
  observation_count: number;
}

export interface AssetRelationshipContext {
  relationship: AssetRelationship;
  direction: "incoming" | "outgoing";
  related_asset: Asset;
}

export interface AssetIntelligence {
  asset: Asset;
  observations: AssetObservation[];
  relationships: AssetRelationshipContext[];
  observations_truncated: boolean;
  relationships_truncated: boolean;
}

export interface ScanKnowledgeSummary {
  assets_total: number;
  relationships_total: number;
  observations_total: number;
  tasks_total: number;
  assets_by_kind: Record<string, number>;
  relationships_by_type: Record<string, number>;
  tasks_by_status: Record<string, number>;
  observations_by_module: Record<string, number>;
}

export interface ReconTask {
  id: number;
  target_id: number;
  input_asset_id: number | null;
  parent_task_id: number | null;
  cache_hit_task_id: number | null;
  module_name: string;
  module_version: string;
  capability: string;
  scope_basis: "direct" | "derived";
  status: ReconTaskStatus;
  priority: number;
  attempts: number;
  max_attempts: number;
  timeout_seconds: number;
  available_at: string;
  started_at: string | null;
  completed_at: string | null;
  error_code: string | null;
  error_detail: string | null;
  output_summary: Record<string, unknown>;
}

export interface TaskDetail extends ReconTask {
  raw_output: string | null;
  config: Record<string, unknown>;
}

export interface TaskList {
  items: ReconTask[];
  total: number;
  page: number;
  page_size: number;
}

export interface ReconEvent {
  id: number;
  target_id: number;
  task_id: number | null;
  event_type: string;
  level: string;
  message: string;
  data: Record<string, unknown>;
  created_at: string;
}

export interface ScopeRule {
  id: number;
  target_id: number;
  action: "include" | "exclude";
  rule_type: "exact" | "subdomain" | "cidr" | "url_prefix" | "regex";
  asset_kind: string | null;
  pattern: string;
  normalized_pattern: string;
  priority: number;
  reason: string | null;
  created_at: string;
}

export interface ScanComparison {
  baseline_target_id: number;
  comparison_target_id: number;
  added: Asset[];
  removed: Asset[];
  changed: Asset[];
  unchanged_count: number;
  truncated: boolean;
}

export interface KnowledgeStats {
  assets_total: number;
  relationships_total: number;
  observations_total: number;
  tasks_by_status: Record<string, number>;
  assets_by_kind: Record<string, number>;
}

export interface BulkResult {
  created: number[];
  conflicts: string[];
  errors: Record<string, string>;
}

export interface SystemInfo {
  name: string;
  version: string;
  env: string;
  auth_required: boolean;
  notifications: { telegram: boolean; webhook: boolean };
}

export const api = {
  listTargets: (
    params: {
      status?: TargetStatus;
      search?: string;
      tag?: string;
      page?: number;
      page_size?: number;
    } = {},
  ) => {
    const qs = new URLSearchParams();
    if (params.status) qs.set("status", params.status);
    if (params.search) qs.set("search", params.search);
    if (params.tag) qs.set("tag", params.tag);
    qs.set("page", String(params.page ?? 1));
    qs.set("page_size", String(params.page_size ?? 25));
    return request<TargetList>(`/targets?${qs.toString()}`);
  },
  getTarget: (id: number, signal?: AbortSignal) =>
    request<TargetDetail>(`/targets/${id}`, { signal }),
  createTarget: (payload: {
    url: string;
    target_kind?: TargetKind;
    tags?: string[];
    selected_modules?: string[] | null;
    notes?: string | null;
    profile?: "passive" | "balanced" | "active";
    authorization_confirmed: boolean;
  }) =>
    request<Target>("/targets", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  bulkCreate: (payload: {
    urls: string[];
    target_kind?: TargetKind;
    tags?: string[];
    selected_modules?: string[] | null;
    profile?: "passive" | "balanced" | "active";
    authorization_confirmed: boolean;
  }) =>
    request<BulkResult>("/targets/bulk", {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteTarget: (id: number) =>
    request<void>(`/targets/${id}`, { method: "DELETE" }),
  cancelTarget: (id: number) =>
    request<Target>(`/targets/${id}/cancel`, { method: "POST" }),
  rescanTarget: (id: number) =>
    request<Target>(`/targets/${id}/rescan`, { method: "POST" }),
  stats: () => request<Stats>("/targets/stats"),
  listResults: (targetId: number) =>
    request<ScanResult[]>(`/targets/${targetId}/results`),
  getResult: (targetId: number, module: string) =>
    request<ScanResult>(`/targets/${targetId}/results/${module}`),
  downloadResult: (targetId: number, module: string) =>
    download(
      `/targets/${targetId}/results/${encodeURIComponent(module)}/download`,
      `reconator-${targetId}-${module}.txt`,
    ),
  exportTargets: (format: "csv" | "json", status?: TargetStatus) => {
    const qs = new URLSearchParams({ format });
    if (status) qs.set("status", status);
    return download(`/targets/export?${qs.toString()}`, `reconator-targets.${format}`);
  },
  modules: () => request<ModuleInfo[]>("/modules"),
  listAssets: (
    targetId: number,
    params: {
      kind?: string;
      search?: string;
      min_priority?: number;
      page?: number;
      page_size?: number;
      signal?: AbortSignal;
    } = {},
  ) => {
    const qs = new URLSearchParams({ page_size: String(params.page_size ?? 500) });
    if (params.kind) qs.set("kind", params.kind);
    if (params.search) qs.set("search", params.search);
    if (params.min_priority !== undefined)
      qs.set("min_priority", String(params.min_priority));
    qs.set("page", String(params.page ?? 1));
    return request<AssetList>(`/targets/${targetId}/assets?${qs.toString()}`, {
      signal: params.signal,
    });
  },
  getAssetIntelligence: (targetId: number, assetId: number, signal?: AbortSignal) =>
    request<AssetIntelligence>(`/targets/${targetId}/assets/${assetId}`, { signal }),
  scanKnowledgeSummary: (targetId: number, signal?: AbortSignal) =>
    request<ScanKnowledgeSummary>(`/targets/${targetId}/knowledge-summary`, { signal }),
  getGraph: (targetId: number, limit = 500, signal?: AbortSignal) =>
    request<AssetGraph>(`/targets/${targetId}/graph?limit=${limit}`, { signal }),
  listTasks: (
    targetId: number,
    params: {
      status?: ReconTaskStatus;
      module?: string;
      page?: number;
      page_size?: number;
      signal?: AbortSignal;
    } = {},
  ) => {
    const qs = new URLSearchParams({ page_size: String(params.page_size ?? 500) });
    if (params.status) qs.set("status", params.status);
    if (params.module) qs.set("module", params.module);
    qs.set("page", String(params.page ?? 1));
    return request<TaskList>(`/targets/${targetId}/tasks?${qs.toString()}`, {
      signal: params.signal,
    });
  },
  getTask: (targetId: number, taskId: number, signal?: AbortSignal) =>
    request<TaskDetail>(`/targets/${targetId}/tasks/${taskId}`, { signal }),
  listEvents: (targetId: number, afterId = 0, signal?: AbortSignal) =>
    request<ReconEvent[]>(
      `/targets/${targetId}/events?limit=500&after_id=${afterId}`,
      { signal },
    ),
  listScope: (targetId: number) =>
    request<ScopeRule[]>(`/targets/${targetId}/scope`),
  addScope: (
    targetId: number,
    payload: {
      action: ScopeRule["action"];
      rule_type: ScopeRule["rule_type"];
      asset_kind?: string | null;
      pattern: string;
      priority?: number;
      reason?: string | null;
    },
  ) =>
    request<ScopeRule>(`/targets/${targetId}/scope`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
  deleteScope: (targetId: number, ruleId: number) =>
    request<void>(`/targets/${targetId}/scope/${ruleId}`, { method: "DELETE" }),
  compareScans: (targetId: number, baselineId: number) =>
    request<ScanComparison>(`/targets/${targetId}/compare/${baselineId}`),
  knowledgeStats: () => request<KnowledgeStats>("/knowledge/stats"),
  systemInfo: () => request<SystemInfo>("/system/info"),
  testNotify: () =>
    request<{ sent: boolean; enabled: boolean }>("/system/test-notify", {
      method: "POST",
    }),
};
