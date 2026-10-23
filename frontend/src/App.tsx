import { useCallback, useEffect, useRef, useState } from "react";
import type { CheckRow, Incident, LiveMessage, Summary, Target, TargetInput } from "./api";
import { api } from "./api";
import { TargetForm } from "./components/TargetForm";
import { Incidents } from "./pages/Incidents";
import { Overview } from "./pages/Overview";
import { TargetDetail } from "./pages/TargetDetail";
import { useLive } from "./useLive";
import { publicDemo } from "./demo";

type Route = { page: "overview" } | { page: "incidents" } | { page: "target"; id: number };

function parseRoute(hash: string): Route {
  const m = hash.match(/^#\/targets\/(\d+)/);
  if (m) return { page: "target", id: Number(m[1]) };
  if (hash.startsWith("#/incidents")) return { page: "incidents" };
  return { page: "overview" };
}

interface Toast {
  id: number;
  kind: "bad" | "good";
  text: string;
}

const SPARK_POINTS = 30;

export function App() {
  const [route, setRoute] = useState<Route>(() => parseRoute(location.hash));
  const [summary, setSummary] = useState<Summary | null>(null);
  const [targets, setTargets] = useState<Target[]>([]);
  const [sparks, setSparks] = useState<Record<number, CheckRow[]>>({});
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [ticks, setTicks] = useState<Record<number, number>>({});
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [adding, setAdding] = useState(false);
  const [apiDown, setApiDown] = useState(false);
  const loadedSparks = useRef(new Set<number>());

  useEffect(() => {
    const on = () => setRoute(parseRoute(location.hash));
    window.addEventListener("hashchange", on);
    return () => window.removeEventListener("hashchange", on);
  }, []);

  const refresh = useCallback(async () => {
    try {
      const [s, t, i] = await Promise.all([api.summary(), api.targets(), api.incidents({ limit: 200 })]);
      setSummary(s);
      setTargets(t);
      setIncidents(i);
      setApiDown(false);
      // Seed each new target's sparkline from its recent history once; after
      // that, live messages keep it up to date.
      for (const target of t) {
        if (loadedSparks.current.has(target.id)) continue;
        loadedSparks.current.add(target.id);
        api.results(target.id, SPARK_POINTS).then((rows) =>
          setSparks((p) => ({ ...p, [target.id]: rows })),
        );
      }
    } catch {
      setApiDown(true);
    }
  }, []);

  // Stats (uptime, percentiles) change slowly; refetch them every 15 s.
  useEffect(() => {
    refresh();
    const t = window.setInterval(refresh, 15000);
    return () => window.clearInterval(t);
  }, [refresh]);

  const toast = (kind: Toast["kind"], text: string) => {
    const id = Date.now() + Math.random();
    setToasts((p) => [...p, { id, kind, text }].slice(-4));
    window.setTimeout(() => setToasts((p) => p.filter((x) => x.id !== id)), 8000);
  };

  const live = useLive((m: LiveMessage) => {
    if (m.type === "check") {
      const row: CheckRow = {
        checked_at: m.checked_at, ok: m.ok, latency_ms: m.latency_ms,
        status_code: m.status_code, error: m.error,
      };
      setTargets((p) => p.map((t) => (t.id === m.target_id ? { ...t, status: m.status, last: row } : t)));
      setSparks((p) => ({ ...p, [m.target_id]: [row, ...(p[m.target_id] ?? [])].slice(0, SPARK_POINTS) }));
      setTicks((p) => ({ ...p, [m.target_id]: (p[m.target_id] ?? 0) + 1 }));
    } else if (m.type === "incident_opened" || m.type === "incident_resolved") {
      toast(m.type === "incident_opened" ? "bad" : "good", m.text);
      refresh();
    }
  });

  const create = async (t: TargetInput) => {
    await api.createTarget(t);
    await refresh();
  };

  const down = summary?.down ?? 0;
  useEffect(() => {
    document.title = down > 0 ? `(${down} down) NetScope` : "NetScope";
  }, [down]);

  return (
    <div className="app">
      <header className="top">
        <a href="#/" className="brand">
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <circle cx="12" cy="12" r="9" />
            <circle cx="12" cy="12" r="4.5" />
            <path d="M12 12 L19 5" />
          </svg>
          NetScope
        </a>
        <nav>
          <a href="#/" className={route.page !== "incidents" ? "on" : ""}>
            Overview
          </a>
          <a href="#/incidents" className={route.page === "incidents" ? "on" : ""}>
            Incidents
            {summary && summary.open_incidents > 0 && <span className="badge">{summary.open_incidents}</span>}
          </a>
        </nav>
        <span className={`live ${live}`} title="Live updates over WebSocket">
          <i className="dot" />
          {live === "live" ? "Live" : live === "connecting" ? "Connecting" : "Reconnecting"}
        </span>
      </header>

      {apiDown && <div className="banner">Can't reach the NetScope API. Retrying…</div>}
      {publicDemo && <div className="banner">Live portfolio demo · Monitoring runs automatically. Target editing is available in the local version.</div>}

      <main>
        {route.page === "overview" && (
          <Overview summary={summary} targets={targets} sparks={sparks} onAdd={() => setAdding(true)} />
        )}
        {route.page === "incidents" && <Incidents incidents={incidents} />}
        {route.page === "target" && (
          <TargetDetail
            key={route.id}
            id={route.id}
            liveTarget={targets.find((t) => t.id === route.id)}
            liveTick={ticks[route.id] ?? 0}
            onChanged={refresh}
          />
        )}
      </main>

      <div className="toasts" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast ${t.kind}`}>
            {t.text}
          </div>
        ))}
      </div>

      {adding && <TargetForm title="Add target" onSubmit={create} onClose={() => setAdding(false)} />}
    </div>
  );
}
