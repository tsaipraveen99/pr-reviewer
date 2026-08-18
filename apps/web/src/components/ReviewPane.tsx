import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { RunView } from "../lib/types";

function ShareButton({ runId }: { runId: string }) {
  const [copied, setCopied] = useState(false);

  const share = async () => {
    await navigator.clipboard.writeText(`${location.origin}/#r=${runId}`);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button type="button" onClick={share} className="mac-button-secondary">
      {copied ? "Copied ✓" : "Share"}
    </button>
  );
}

interface ReviewPaneProps {
  view: RunView;
  /** The live run's id, once known; omitted for showcase replays and
   * permalink loads, which have nothing new of their own to share. */
  runId?: string | null;
}

export function ReviewPane({ view, runId }: ReviewPaneProps) {
  if (!view.error && !view.review) return null;
  const canShare = view.done && !view.error && !!runId;

  return (
    <div className="panel p-5">
      {view.error && <p className="text-sm text-err">Run failed: {view.error}</p>}
      {view.review && (
        <div>
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="eyebrow">Verdict</p>
            {canShare && <ShareButton runId={runId as string} />}
          </div>
          <div className="markdown">
            <ReactMarkdown>{view.review}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
