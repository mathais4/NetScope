// Types mirror the JSON returned by the FastAPI backend.

export type Kind = "http" | "tcp" | "ping";
export type Status = "unknown" | "up" | "degraded" | "down" | "paused";

export interface Stats {
  checks: number;
  ok_checks: number;
  uptime_pct: number | null;
  avg_ms: number | null;
  p50_ms: number | null;
  p95_ms: number | null;
  p99_ms: number | null;
}

export interface CheckRow {
  checked_at: string;
  ok: boolean;
  latency_ms: number | null;
  status_code: number | null;
  error: string | null;
}

export interface TargetInput {
  name: string;
  kind: Kind;
  url?: string | null;
  host?: string | null;
  port?: number | null;
  interval_s: number;
  timeout_s: number;
  expected_status?: number | null;
  enabled: boolean;
}

export interface Target extends TargetInput {
  id: number;
  created_at: string;
  status: Status;
  last: CheckRow | null;
  stats_24h: Stats;
}

export interface Summary {
  targets: number;
  up: number;
  degraded: number;
  down: number;
  unknown: number;
  paused: number;
  open_incidents: number;
  uptime_24h_pct: number | null;
  checks_24h: number;
}

export interface Incident {
  id: number;
  target_id: number;
  target_name: string;
  started_at: string;
  resolved_at: string | null;
  cause: string | null;
  duration_s: number;
}

export interface Bucket {
  bucket: string;
  checks: number;
  ok_checks: number;
  uptime_pct: number | null;
  avg_ms: number | null;
  p95_ms: number | null;
}

export interface History {
  range: Range;
  bucket_s: number;
  since: string;
  buckets: Bucket[];
}

export type Range = "1h" | "24h" | "7d";

export type LiveMessage =
  | { type: "hello" }
  | ({ type: "check"; target_id: number; status: Status } & CheckRow)
  | {
      type: "incident_opened" | "incident_resolved";
      incident_id: number | null;
      target_id: number;
      target_name: string;
      at: string;
      cause: string | null;
      text: string;
    };

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") detail = body.detail;
      else if (Array.isArray(body.detail))
        detail = body.detail
          .map((d: { msg: string; loc?: (string | number)[] }) => {
            const field = d.loc?.[d.loc.length - 1];
            const msg = d.msg.replace(/^Value error, /, "");
            return typeof field === "string" && field !== "body" ? `${field}: ${msg}` : msg;
          })
          .join("; ");
    } catch {
      /* not JSON */
    }
    throw new Error(detail);
  }
  return res.status === 204 ? (undefined as T) : ((await res.json()) as T);
}

export const api = {
  summary: () => request<Summary>("/api/summary"),
  targets: () => request<Target[]>("/api/targets"),
  target: (id: number) => request<Target>(`/api/targets/${id}`),
  createTarget: (t: TargetInput) => request<Target>("/api/targets", { method: "POST", body: JSON.stringify(t) }),
  updateTarget: (id: number, t: TargetInput) =>
    request<Target>(`/api/targets/${id}`, { method: "PUT", body: JSON.stringify(t) }),
  deleteTarget: (id: number) => request<void>(`/api/targets/${id}`, { method: "DELETE" }),
  checkNow: (id: number) => request<CheckRow & { status: Status }>(`/api/targets/${id}/check`, { method: "POST" }),
  results: (id: number, limit = 50) => request<CheckRow[]>(`/api/targets/${id}/results?limit=${limit}`),
  history: (id: number, range: Range) => request<History>(`/api/targets/${id}/history?range=${range}`),
  incidents: (opts: { targetId?: number; openOnly?: boolean; limit?: number } = {}) => {
    const p = new URLSearchParams();
    if (opts.targetId != null) p.set("target_id", String(opts.targetId));
    if (opts.openOnly) p.set("open_only", "true");
    p.set("limit", String(opts.limit ?? 100));
    return request<Incident[]>(`/api/incidents?${p}`);
  },
};

export function toInput(t: Target): TargetInput {
  const { name, kind, url, host, port, interval_s, timeout_s, expected_status, enabled } = t;
  return { name, kind, url, host, port, interval_s, timeout_s, expected_status, enabled };
}

export function address(t: TargetInput): string {
  if (t.kind === "http") return t.url ?? "";
  if (t.kind === "tcp") return `${t.host}:${t.port}`;
  return t.host ?? "";
}
