import type { CheckRow, Summary, Target } from "../api";
import { address } from "../api";
import { Sparkline } from "../components/Charts";
import { Empty, KindTag, StatusPill, Tile } from "../components/Bits";
import { ago, ms, pct } from "../format";
import { publicDemo } from "../demo";

const ORDER = { down: 0, degraded: 1, unknown: 2, up: 3, paused: 4 } as const;

export function Overview({
  summary,
  targets,
  sparks,
  onAdd,
}: {
  summary: Summary | null;
  targets: Target[];
  sparks: Record<number, CheckRow[]>;
  onAdd: () => void;
}) {
  const sorted = [...targets].sort((a, b) => ORDER[a.status] - ORDER[b.status] || a.name.localeCompare(b.name));

  return (
    <>
      <section className="tiles">
        <Tile
          label="Targets up"
          value={summary ? `${summary.up}/${summary.targets - summary.paused}` : "—"}
          hint={
            !summary ? undefined
              : summary.down > 0 ? `${summary.down} down${summary.degraded ? `, ${summary.degraded} degraded` : ""}`
              : summary.degraded > 0 ? `${summary.degraded} degraded`
              : summary.unknown > 0 ? `${summary.unknown} waiting for first check`
              : "everything passing"
          }
          tone={summary && summary.down === 0 && summary.degraded === 0 ? "good" : undefined}
        />
        <Tile
          label="Down now"
          value={summary?.down ?? "—"}
          hint={summary ? `${summary.open_incidents} open incident${summary.open_incidents === 1 ? "" : "s"}` : undefined}
          tone={summary && summary.down > 0 ? "bad" : undefined}
        />
        <Tile label="Uptime, 24 h" value={pct(summary?.uptime_24h_pct)} hint="share of all checks that passed" />
        <Tile label="Checks, 24 h" value={summary ? summary.checks_24h.toLocaleString() : "—"} hint="stored in PostgreSQL" />
      </section>

      <section className="panel">
        <header className="panel-head">
          <h2>Targets</h2>
          {!publicDemo && <button className="primary" onClick={onAdd}>
            + Add target
          </button>}
        </header>
        {sorted.length === 0 ? (
          <Empty>No targets yet. Add a website, server port or device to start monitoring.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="targets">
              <thead>
                <tr>
                  <th>Status</th>
                  <th>Target</th>
                  <th className="num hide-sm">Last</th>
                  <th className="num hide-sm">p95 · 24 h</th>
                  <th className="num">Uptime · 24 h</th>
                  <th className="hide-sm">Recent</th>
                  <th className="hide-sm">Checked</th>
                </tr>
              </thead>
              <tbody>
                {sorted.map((t) => (
                  <tr key={t.id} onClick={() => (location.hash = `#/targets/${t.id}`)}>
                    <td>
                      <StatusPill status={t.status} />
                    </td>
                    <td>
                      <a href={`#/targets/${t.id}`} className="target-name">
                        {t.name}
                      </a>
                      <div className="sub">
                        <KindTag kind={t.kind} /> {address(t)}
                      </div>
                      {t.last && !t.last.ok && <div className="error-line">{t.last.error}</div>}
                    </td>
                    <td className="num hide-sm">{t.last?.ok ? ms(t.last.latency_ms) : "—"}</td>
                    <td className="num hide-sm">{ms(t.stats_24h.p95_ms)}</td>
                    <td className="num">{pct(t.stats_24h.uptime_pct)}</td>
                    <td className="hide-sm">
                      <Sparkline rows={sparks[t.id] ?? []} />
                    </td>
                    <td className="hide-sm muted">{ago(t.last?.checked_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}
