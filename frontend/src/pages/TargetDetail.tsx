import { useCallback, useEffect, useState } from "react";
import type { CheckRow, History, Incident, Range, Target, TargetInput } from "../api";
import { address, api, toInput } from "../api";
import { LatencyChart, UptimeBar } from "../components/Charts";
import { Empty, KindTag, StatusPill, Tile } from "../components/Bits";
import { TargetForm } from "../components/TargetForm";
import { clock, ms, pct } from "../format";
import { IncidentTable } from "./Incidents";
import { publicDemo } from "../demo";

export function TargetDetail({
  id,
  liveTarget,
  liveTick,
  onChanged,
}: {
  id: number;
  liveTarget: Target | undefined; // status/last kept fresh by the live feed
  liveTick: number; // bumps whenever a check for this target arrives
  onChanged: () => void;
}) {
  const [target, setTarget] = useState<Target | null>(null);
  const [range, setRange] = useState<Range>("1h");
  const [history, setHistory] = useState<History | null>(null);
  const [results, setResults] = useState<CheckRow[]>([]);
  const [incidents, setIncidents] = useState<Incident[]>([]);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [missing, setMissing] = useState(false);

  const load = useCallback(async () => {
    try {
      const [t, h, r, i] = await Promise.all([
        api.target(id),
        api.history(id, range),
        api.results(id, 15),
        api.incidents({ targetId: id, limit: 20 }),
      ]);
      setTarget(t);
      setHistory(h);
      setResults(r);
      setIncidents(i);
    } catch {
      setMissing(true);
    }
  }, [id, range]);

  useEffect(() => {
    load();
  }, [load]);

  // A new check arrived for this target: reload (debounced, so a burst of
  // messages causes one refresh).
  useEffect(() => {
    if (liveTick === 0) return;
    const t = window.setTimeout(load, 300);
    return () => window.clearTimeout(t);
  }, [liveTick, load]);

  if (missing) return <Empty>This target no longer exists. <a href="#/">Back to overview</a></Empty>;
  if (!target) return <div className="loading">Loading…</div>;

  const status = liveTarget?.status ?? target.status;
  const s = target.stats_24h;

  const toggle = async () => {
    setBusy(true);
    await api.updateTarget(id, { ...toInput(target), enabled: !target.enabled });
    await load();
    onChanged();
    setBusy(false);
  };
  const checkNow = async () => {
    setBusy(true);
    try {
      await api.checkNow(id);
    } catch {
      /* a scheduled check was already running */
    }
    await load();
    setBusy(false);
  };
  const remove = async () => {
    if (!window.confirm(`Stop monitoring "${target.name}" and delete its history?`)) return;
    await api.deleteTarget(id);
    onChanged();
    location.hash = "#/";
  };
  const save = async (t: TargetInput) => {
    await api.updateTarget(id, t);
    await load();
    onChanged();
  };

  return (
    <>
      <a href="#/" className="back">
        ← All targets
      </a>
      <section className="detail-head">
        <div>
          <h1>
            {target.name} <StatusPill status={status} />
          </h1>
          <div className="sub">
            <KindTag kind={target.kind} /> {address(target)} · every {target.interval_s}s · timeout {target.timeout_s}s
          </div>
        </div>
        {!publicDemo && <div className="buttons">
          <button onClick={checkNow} disabled={busy}>
            Check now
          </button>
          <button onClick={toggle} disabled={busy}>
            {target.enabled ? "Pause" : "Resume"}
          </button>
          <button onClick={() => setEditing(true)}>Edit</button>
          <button className="danger" onClick={remove}>
            Delete
          </button>
        </div>}
      </section>

      <section className="tiles">
        <Tile label="Uptime, 24 h" value={pct(s.uptime_pct)} hint={`${s.ok_checks}/${s.checks} checks passed`} tone={s.uptime_pct === 100 ? "good" : s.uptime_pct != null && s.uptime_pct < 99 ? "bad" : undefined} />
        <Tile label="Median (p50)" value={ms(s.p50_ms)} hint={`average ${ms(s.avg_ms)}`} />
        <Tile label="p95" value={ms(s.p95_ms)} hint="95% of checks were faster" />
        <Tile label="p99" value={ms(s.p99_ms)} hint="the slow tail" />
      </section>

      <section className="panel">
        <header className="panel-head">
          <h2>Response time</h2>
          <div className="tabs" role="tablist">
            {(["1h", "24h", "7d"] as Range[]).map((r) => (
              <button key={r} role="tab" aria-selected={range === r} className={range === r ? "on" : ""} onClick={() => setRange(r)}>
                {r}
              </button>
            ))}
          </div>
        </header>
        {history && (
          <>
            <LatencyChart history={history} />
            <div className="uptime-label">Availability</div>
            <UptimeBar history={history} />
          </>
        )}
      </section>

      <div className="two-col">
        <section className="panel">
          <header className="panel-head">
            <h2>Latest checks</h2>
          </header>
          {results.length === 0 ? (
            <Empty>No checks yet.</Empty>
          ) : (
            <table className="checks">
              <tbody>
                {results.map((r) => (
                  <tr key={r.checked_at}>
                    <td className="muted">{clock(r.checked_at)}</td>
                    <td>
                      <span className={`dot-only ${r.ok ? "up" : "down"}`} />
                    </td>
                    <td className="num">{r.ok ? ms(r.latency_ms) : ""}</td>
                    <td className="muted">{r.ok ? (r.status_code ? `HTTP ${r.status_code}` : "reachable") : r.error}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
        <section className="panel">
          <header className="panel-head">
            <h2>Incidents</h2>
          </header>
          <IncidentTable incidents={incidents} showTarget={false} />
        </section>
      </div>

      {editing && <TargetForm title="Edit target" initial={toInput(target)} onSubmit={save} onClose={() => setEditing(false)} />}
    </>
  );
}
