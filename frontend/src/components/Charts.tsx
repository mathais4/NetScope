import { useMemo, useRef, useState, type MouseEvent } from "react";
import type { Bucket, CheckRow, History } from "../api";
import { clock, dateTime, ms, pct } from "../format";

// Hand-written SVG charts: no charting library, so every pixel is explainable.

const W = 800;
const H = 220;
const PAD = { top: 12, right: 12, bottom: 26, left: 48 };

function niceMax(v: number): number {
  if (v <= 0) return 10;
  const exp = 10 ** Math.floor(Math.log10(v));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * exp >= v) return m * exp;
  return 10 * exp;
}

export function LatencyChart({ history }: { history: History }) {
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<number | null>(null);

  const t0 = new Date(history.since).getTime();
  const t1 = Date.now();
  const buckets = history.buckets;

  const { yMax, x, y } = useMemo(() => {
    const peak = Math.max(0, ...buckets.map((b) => b.p95_ms ?? b.avg_ms ?? 0));
    const yMax = niceMax(peak * 1.1);
    const x = (iso: string) =>
      PAD.left + ((new Date(iso).getTime() + (history.bucket_s * 500) - t0) / (t1 - t0)) * (W - PAD.left - PAD.right);
    const y = (v: number) => PAD.top + (1 - v / yMax) * (H - PAD.top - PAD.bottom);
    return { yMax, x, y };
  }, [buckets, t0, t1, history.bucket_s]);

  const line = (key: "avg_ms" | "p95_ms") => {
    let d = "";
    let pen = false;
    for (const b of buckets) {
      const v = b[key];
      if (v == null) {
        pen = false;
        continue;
      }
      d += `${pen ? "L" : "M"}${x(b.bucket).toFixed(1)},${y(v).toFixed(1)}`;
      pen = true;
    }
    return d;
  };

  const yTicks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * yMax);
  const xTicks = Array.from({ length: 5 }, (_, i) => t0 + ((t1 - t0) * (i + 0.5)) / 5);
  const showDate = history.range === "7d";

  const onMove = (e: MouseEvent<SVGSVGElement>) => {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect || buckets.length === 0) return;
    const px = ((e.clientX - rect.left) / rect.width) * W;
    let best = 0;
    let bestD = Infinity;
    buckets.forEach((b, i) => {
      const d = Math.abs(x(b.bucket) - px);
      if (d < bestD) {
        bestD = d;
        best = i;
      }
    });
    setHover(best);
  };

  const hb: Bucket | null = hover != null ? buckets[hover] ?? null : null;

  return (
    <div className="chart">
      <div className="legend">
        <span><i className="swatch avg" /> average</span>
        <span><i className="swatch p95" /> p95</span>
        <span><i className="swatch fail" /> failed checks</span>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${W} ${H}`}
        role="img"
        aria-label="Response time chart"
        onMouseMove={onMove}
        onMouseLeave={() => setHover(null)}
      >
        {yTicks.map((v) => (
          <g key={v}>
            <line className="grid" x1={PAD.left} x2={W - PAD.right} y1={y(v)} y2={y(v)} />
            <text className="axis" x={PAD.left - 8} y={y(v) + 4} textAnchor="end">
              {v === 0 ? "0" : ms(v)}
            </text>
          </g>
        ))}
        {xTicks.map((t) => (
          <text key={t} className="axis" x={PAD.left + ((t - t0) / (t1 - t0)) * (W - PAD.left - PAD.right)} y={H - 6} textAnchor="middle">
            {showDate
              ? new Date(t).toLocaleDateString([], { weekday: "short", day: "numeric" })
              : new Date(t).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </text>
        ))}
        <path className="line p95" d={line("p95_ms")} />
        <path className="line avg" d={line("avg_ms")} />
        {buckets
          .filter((b) => b.ok_checks < b.checks)
          .map((b) => (
            <rect
              key={b.bucket}
              className="fail-mark"
              x={x(b.bucket) - 2}
              y={H - PAD.bottom - 6}
              width={4}
              height={6}
              rx={1}
            />
          ))}
        {hb && (
          <line className="cursor" x1={x(hb.bucket)} x2={x(hb.bucket)} y1={PAD.top} y2={H - PAD.bottom} />
        )}
        {buckets.length === 0 && (
          <text className="axis" x={W / 2} y={H / 2} textAnchor="middle">
            No checks in this period yet
          </text>
        )}
      </svg>
      {hb && (
        <div className="tooltip" style={{ left: `${(x(hb.bucket) / W) * 100}%` }}>
          <strong>{showDate ? dateTime(hb.bucket) : clock(hb.bucket)}</strong>
          <span>avg {ms(hb.avg_ms)} · p95 {ms(hb.p95_ms)}</span>
          <span>
            {hb.ok_checks}/{hb.checks} checks ok
          </span>
        </div>
      )}
    </div>
  );
}

export function UptimeBar({ history }: { history: History }) {
  // Buckets are aligned to whole multiples of the bucket size (the backend's
  // date_bin origin is 2000-01-01, itself a multiple), so a bucket's index is
  // just floor(time / size). One cell per bucket in the window, empty or not.
  const size = history.bucket_s * 1000;
  const first = Math.floor(new Date(history.since).getTime() / size);
  const last = Math.floor(Date.now() / size);
  const byIndex = new Map(history.buckets.map((b) => [Math.floor(new Date(b.bucket).getTime() / size), b]));

  const cells = Array.from({ length: last - first + 1 }, (_, i) => {
    const b = byIndex.get(first + i);
    const checks = b?.checks ?? 0;
    const ok = b?.ok_checks ?? 0;
    const state = checks === 0 ? "none" : ok === checks ? "good" : ok === 0 ? "bad" : "partial";
    return { state, checks, ok, start: new Date((first + i) * size).toISOString() };
  });

  return (
    <div className="uptime-bar" role="img" aria-label="Uptime over time">
      {cells.map((c) => (
        <span
          key={c.start}
          className={`cell ${c.state}`}
          title={`${dateTime(c.start)} — ${c.checks ? `${pct((100 * c.ok) / c.checks)} up (${c.ok}/${c.checks})` : "no data"}`}
        />
      ))}
    </div>
  );
}

export function Sparkline({ rows }: { rows: CheckRow[] }) {
  const w = 120;
  const h = 28;
  if (rows.length < 2) return <svg className="spark" viewBox={`0 0 ${w} ${h}`} />;
  const ordered = [...rows].reverse(); // oldest first
  const vals = ordered.map((r) => r.latency_ms ?? 0);
  const max = Math.max(1, ...vals);
  const x = (i: number) => (i / (ordered.length - 1)) * (w - 4) + 2;
  const y = (v: number) => h - 3 - (v / max) * (h - 6);
  let d = "";
  let pen = false;
  ordered.forEach((r, i) => {
    if (!r.ok || r.latency_ms == null) {
      pen = false;
      return;
    }
    d += `${pen ? "L" : "M"}${x(i).toFixed(1)},${y(r.latency_ms).toFixed(1)}`;
    pen = true;
  });
  return (
    <svg className="spark" viewBox={`0 0 ${w} ${h}`} aria-hidden="true">
      <path d={d} />
      {ordered.map((r, i) => (!r.ok ? <circle key={i} cx={x(i)} cy={h - 4} r={2} /> : null))}
    </svg>
  );
}
