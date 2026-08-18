import ReactMarkdown from "react-markdown";
import type { RunView } from "../lib/types";

export function ReviewPane({ view }: { view: RunView }) {
  if (!view.error && !view.review) return null;

  return (
    <div className="rounded-lg border border-zinc-800 bg-zinc-900/60 p-5">
      {view.error && <p className="text-sm text-red-400">Run failed: {view.error}</p>}
      {view.review && (
        <div className="markdown">
          <ReactMarkdown>{view.review}</ReactMarkdown>
        </div>
      )}
    </div>
  );
}
