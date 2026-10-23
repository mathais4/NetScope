import type { Incident } from "../api";
import { Empty } from "../components/Bits";
import { dateTime, duration } from "../format";

export function IncidentTable({ incidents, showTarget = true }: { incidents: Incident[]; showTarget?: boolean }) {
  if (incidents.length === 0) return <Empty>No incidents recorded. Long may it last.</Empty>;
  return (
    <div className="table-wrap">
      <table className="incidents">
        <thead>
          <tr>
            <th>State</th>
            {showTarget && <th>Target</th>}
            <th>Started</th>
            <th className="num">Duration</th>
            <th>Cause</th>
          </tr>
        </thead>
        <tbody>
          {incidents.map((i) => (
            <tr key={i.id}>
              <td>
                <span className={`pill ${i.resolved_at ? "up" : "down"}`}>
                  <i className="dot" />
                  {i.resolved_at ? "Resolved" : "Ongoing"}
                </span>
              </td>
              {showTarget && (
                <td>
                  <a href={`#/targets/${i.target_id}`}>{i.target_name}</a>
                </td>
              )}
              <td>{dateTime(i.started_at)}</td>
              <td className="num">{duration(i.duration_s)}</td>
              <td className="muted">{i.cause ?? "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Incidents({ incidents }: { incidents: Incident[] }) {
  const open = incidents.filter((i) => !i.resolved_at);
  const done = incidents.filter((i) => i.resolved_at);
  const totalDown = done.reduce((s, i) => s + i.duration_s, 0);
  return (
    <>
      <section className="panel">
        <header className="panel-head">
          <h2>Ongoing</h2>
        </header>
        {open.length === 0 ? <Empty>Nothing is down right now.</Empty> : <IncidentTable incidents={open} />}
      </section>
      <section className="panel">
        <header className="panel-head">
          <h2>History</h2>
          <span className="muted">
            {done.length} resolved · {duration(totalDown)} total downtime
          </span>
        </header>
        <IncidentTable incidents={done} />
      </section>
    </>
  );
}
