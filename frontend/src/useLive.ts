import { useEffect, useRef, useState } from "react";
import type { LiveMessage } from "./api";

export type LiveState = "connecting" | "live" | "offline";

/**
 * Subscribes to the backend's /ws feed. Reconnects with exponential backoff
 * (1s, 2s, 4s ... capped at 15s) so a restarted API comes back on its own.
 */
export function useLive(onMessage: (m: LiveMessage) => void): LiveState {
  const [state, setState] = useState<LiveState>("connecting");
  const handler = useRef(onMessage);
  handler.current = onMessage;

  useEffect(() => {
    let ws: WebSocket | null = null;
    let retry = 0;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      ws.onopen = () => {
        retry = 0;
        setState("live");
      };
      ws.onmessage = (e) => {
        try {
          handler.current(JSON.parse(e.data) as LiveMessage);
        } catch {
          /* ignore malformed message */
        }
      };
      ws.onclose = () => {
        if (closed) return;
        setState("offline");
        const delay = Math.min(15000, 1000 * 2 ** retry++);
        timer = window.setTimeout(connect, delay);
      };
    };
    connect();

    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return state;
}
