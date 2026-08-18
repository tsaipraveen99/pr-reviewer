import { useCallback, useRef, useState } from "react";
import { fetchReview, fetchShowcase, reviewResultToEvents, startReview, streamUrl } from "../lib/api";
import { initialView, reduce } from "../lib/reducer";
import type { RunView, StreamEvent } from "../lib/types";

const TERMINAL = new Set(["done", "run_failed"]);

export function useReviewRun() {
  const [view, setView] = useState<RunView>(initialView);
  const [running, setRunning] = useState(false);
  const source = useRef<EventSource | null>(null);
  const timers = useRef<number[]>([]);
  const terminalReached = useRef(false);

  const stop = () => {
    source.current?.close();
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setRunning(false);
  };

  const dispatch = (ev: StreamEvent) => {
    setView(v => reduce(v, ev));
    if (TERMINAL.has(ev.type)) {
      terminalReached.current = true;
      stop();
    }
  };

  const start = useCallback(async (prUrl: string) => {
    stop();
    terminalReached.current = false;
    setView(initialView());
    setRunning(true);
    const { run_id } = await startReview(prUrl); // ApiError propagates to the form
    const es = new EventSource(streamUrl(run_id));
    source.current = es;
    es.onmessage = e => dispatch(JSON.parse(e.data));
    // sse-starlette sends named events; listen to each type explicitly
    ["node_started", "finding", "node_finished", "node_failed",
     "verified", "review_complete", "done", "run_failed"].forEach(t =>
      es.addEventListener(t, e => dispatch(JSON.parse((e as MessageEvent).data))));
    es.onerror = () => {
      stop();
      // A normal server-side stream close also fires onerror; only recover
      // via refetch when no terminal event has been seen yet.
      if (terminalReached.current) return;
      fetchReview(run_id)
        .then(({ status, result }) => reviewResultToEvents(status, result).forEach(dispatch))
        .catch(() => reviewResultToEvents("error", null).forEach(dispatch));
    };
  }, []);

  const replay = useCallback(async (slug: string) => {
    stop();
    setView(initialView());
    setRunning(true);
    const sc = await fetchShowcase(slug);
    const maxMs = Math.max(...sc.events.map((e: { at_ms: number }) => e.at_ms), 1);
    const scale = Math.min(1, 30_000 / maxMs);
    sc.events.forEach((e: StreamEvent & { at_ms: number }) =>
      timers.current.push(window.setTimeout(() => dispatch(e), e.at_ms * scale)));
    timers.current.push(window.setTimeout(
      () => dispatch({ type: "done" }), maxMs * scale + 100));
  }, []);

  return { view, running, start, replay };
}
