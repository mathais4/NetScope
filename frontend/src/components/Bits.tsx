import type { ReactNode } from "react";
import type { Kind, Status } from "../api";

const LABEL: Record<Status, string> = {
  up: "Up",
  degraded: "Degraded",
  down: "Down",
  unknown: "Pending",
  paused: "Paused",
};

export function StatusPill({ status }: { status: Status }) {
  return (
    <span className={`pill ${status}`}>
      <i className="dot" />
      {LABEL[status]}
    </span>
  );
}

export function KindTag({ kind }: { kind: Kind }) {
  return <span className="kind">{kind.toUpperCase()}</span>;
}

export function Tile({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "good" | "bad" | "warn" }) {
  return (
    <div className={`tile ${tone ?? ""}`}>
      <div className="tile-label">{label}</div>
      <div className="tile-value">{value}</div>
      {hint != null && <div className="tile-hint">{hint}</div>}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="empty">{children}</div>;
}
