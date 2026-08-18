import { useState } from "react";
import ReactMarkdown from "react-markdown";
import type { RunView } from "../lib/types";

const COMMENT_FOOTER =
  "\n\n---\n*Reviewed by [pr-reviewer](https://pr-review-crew.vercel.app) " +
  "— a multi-agent LangGraph review crew.*";

/** Copies whatever `getText()` returns on click, showing a transient
 * "Copied ✓" label; shared by the Share and Copy-as-PR-comment buttons. */
function CopyButton({ label, getText }: { label: string; getText: () => string }) {
  const [copied, setCopied] = useState(false);

  const copy = async () => {
    await navigator.clipboard.writeText(getText());
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  };

  return (
    <button type="button" onClick={copy} className="mac-button-secondary">
      {copied ? "Copied ✓" : label}
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
            <div className="flex items-center gap-2">
              <CopyButton label="Copy as PR comment"
                getText={() => `${view.review}${COMMENT_FOOTER}`} />
              {canShare && (
                <CopyButton label="Share" getText={() => `${location.origin}/#r=${runId}`} />
              )}
            </div>
          </div>
          <div className="markdown">
            <ReactMarkdown>{view.review}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
