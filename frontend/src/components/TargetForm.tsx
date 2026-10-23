import { useState, type FormEvent } from "react";
import type { Kind, TargetInput } from "../api";

const BLANK: TargetInput = {
  name: "",
  kind: "http",
  url: "https://",
  host: "",
  port: null,
  interval_s: 30,
  timeout_s: 5,
  expected_status: null,
  enabled: true,
};

const HINT: Record<Kind, string> = {
  http: "Sends a GET request. Up if the status is 2xx/3xx, or exactly the status you expect.",
  tcp: "Opens a TCP connection. Up if something is listening on the port.",
  ping: "Sends one ICMP echo request. Up if the host replies.",
};

export function TargetForm({
  initial,
  title,
  onSubmit,
  onClose,
}: {
  initial?: TargetInput;
  title: string;
  onSubmit: (t: TargetInput) => Promise<void>;
  onClose: () => void;
}) {
  const [t, setT] = useState<TargetInput>(initial ?? BLANK);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const set = <K extends keyof TargetInput>(k: K, v: TargetInput[K]) => setT((p) => ({ ...p, [k]: v }));
  const num = (s: string) => (s.trim() === "" ? null : Number(s));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await onSubmit(t);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="modal-backdrop" onMouseDown={onClose}>
      <form className="modal" onMouseDown={(e) => e.stopPropagation()} onSubmit={submit}>
        <h2>{title}</h2>

        <label>
          Name
          <input value={t.name} onChange={(e) => set("name", e.target.value)} placeholder="Office router" required autoFocus />
        </label>

        <fieldset className="segmented">
          <legend>Check type</legend>
          {(["http", "tcp", "ping"] as Kind[]).map((k) => (
            <label key={k} className={t.kind === k ? "on" : ""}>
              <input type="radio" name="kind" checked={t.kind === k} onChange={() => set("kind", k)} />
              {k.toUpperCase()}
            </label>
          ))}
        </fieldset>
        <p className="hint">{HINT[t.kind]}</p>

        {t.kind === "http" ? (
          <div className="row">
            <label className="grow">
              URL
              <input value={t.url ?? ""} onChange={(e) => set("url", e.target.value)} placeholder="https://example.com/health" required />
            </label>
            <label className="narrow">
              Expect status
              <input inputMode="numeric" value={t.expected_status ?? ""} onChange={(e) => set("expected_status", num(e.target.value))} placeholder="any 2xx/3xx" />
            </label>
          </div>
        ) : (
          <div className="row">
            <label className="grow">
              Host or IP
              <input value={t.host ?? ""} onChange={(e) => set("host", e.target.value)} placeholder="192.168.1.1" required />
            </label>
            {t.kind === "tcp" && (
              <label className="narrow">
                Port
                <input inputMode="numeric" value={t.port ?? ""} onChange={(e) => set("port", num(e.target.value))} placeholder="443" required />
              </label>
            )}
          </div>
        )}

        <div className="row">
          <label>
            Check every (s)
            <input type="number" min={5} max={3600} value={t.interval_s} onChange={(e) => set("interval_s", Number(e.target.value))} />
          </label>
          <label>
            Timeout (s)
            <input type="number" min={0.5} max={30} step={0.5} value={t.timeout_s} onChange={(e) => set("timeout_s", Number(e.target.value))} />
          </label>
        </div>

        <label className="check">
          <input type="checkbox" checked={t.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          Monitoring enabled
        </label>

        {error && <p className="form-error">{error}</p>}

        <div className="actions">
          <button type="button" className="ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="primary" disabled={busy}>
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </form>
    </div>
  );
}
