import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, fetchReview, fetchShowcase, reviewResultToEvents, startReview, streamUrl } from "../lib/api";
import { initialView, reduce } from "../lib/reducer";
import type { RunView, StreamEvent } from "../lib/types";

const TERMINAL = new Set(["done", "run_failed"]);
// Transient SSE drops trigger a clean reconnect (the server replays every
// event from seq 1 on a fresh connection); cap attempts per run so a truly
// dead backend still surfaces as a failure.
const MAX_RECONNECTS = 3;

export function useReviewRun() {
  const [view, setView] = useState<RunView>(initialView);
  const [running, setRunning] = useState(false);
  const source = useRef<EventSource | null>(null);
  const timers = useRef<number[]>([]);
  const terminalReached = useRef(false);
  // Bumped by every start()/replay() so an in-flight fallback fetch from a
  // superseded run can detect it's stale and avoid dispatching into the new run.
  const generation = useRef(0);
  const reconnects = useRef(0);

  const stop = useCallback(() => {
    source.current?.close();
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setRunning(false);
  }, []);

  // Close the stream and cancel timers when the component unmounts.
  useEffect(() => () => stop(), [stop]);

  const dispatch = useCallback((ev: StreamEvent) => {
    setView(v => reduce(v, ev));
    if (TERMINAL.has(ev.type)) {
      terminalReached.current = true;
      stop();
    }
  }, [stop]);

  /** Create the EventSource for a run and wire up listeners + error fallback. */
  const attach = useCallback((runId: string, gen: number) => {
    const es = new EventSource(streamUrl(runId));
    source.current = es;
    es.onmessage = e => dispatch(JSON.parse(e.data));
    // sse-starlette sends named events; listen to each type explicitly
    ["node_started", "finding", "node_finished", "node_failed",
     "verified", "finding_verdict", "review_complete", "done", "run_failed"].forEach(t =>
      es.addEventListener(t, e => dispatch(JSON.parse((e as MessageEvent).data))));
    es.onerror = () => {
      stop();
      // A normal server-side stream close also fires onerror; only recover
      // via refetch when no terminal event has been seen yet.
      if (terminalReached.current) return;
      fetchReview(runId)
        .then(({ status, result }) => {
          if (generation.current !== gen) return; // superseded by a later start()/replay()
          if (status === "running" && reconnects.current < MAX_RECONNECTS) {
            // The backend run is alive; the drop was transient. Reconnect on a
            // clean slate -- the server replays all events from seq 1.
            reconnects.current += 1;
            setView(initialView());
            setRunning(true);
            attach(runId, gen);
            return;
          }
          // Terminal status, or reconnect budget exhausted ("running" maps to
          // run_failed("connection lost") in the translator).
          reviewResultToEvents(status, result).forEach(dispatch);
        })
        .catch(() => {
          if (generation.current !== gen) return; // superseded by a later start()/replay()
          reviewResultToEvents("error", null).forEach(dispatch);
        });
    };
  }, [dispatch, stop]);

  const start = useCallback(async (prUrl: string) => {
    stop();
    terminalReached.current = false;
    generation.current += 1;
    reconnects.current = 0;
    const gen = generation.current;
    setView(initialView());
    setRunning(true);
    let runId: string;
    try {
      ({ run_id: runId } = await startReview(prUrl));
    } catch (err) {
      if (generation.current === gen) stop(); // re-enable the UI
      throw err; // PRForm's catch displays the ApiError message
    }
    if (generation.current !== gen) return; // superseded while awaiting
    attach(runId, gen);
  }, [attach, stop]);

  const replay = useCallback(async (slug: string) => {
    stop();
    generation.current += 1;
    const gen = generation.current;
    setView(initialView());
    setRunning(true);
    let sc;
    try {
      sc = await fetchShowcase(slug);
    } catch (err) {
      if (generation.current !== gen) return; // superseded while awaiting
      stop();
      const message = err instanceof ApiError ? err.message : "Could not load the showcase. Try again.";
      setView(v => ({ ...v, error: message }));
      return;
    }
    if (generation.current !== gen) return; // superseded while awaiting
    const maxMs = Math.max(...sc.events.map((e: { at_ms: number }) => e.at_ms), 1);
    const scale = Math.min(1, 30_000 / maxMs);
    sc.events.forEach((e: StreamEvent & { at_ms: number }) =>
      timers.current.push(window.setTimeout(() => dispatch(e), e.at_ms * scale)));
    timers.current.push(window.setTimeout(
      () => dispatch({ type: "done" }), maxMs * scale + 100));
  }, [dispatch, stop]);

  return { view, running, start, replay };
}
