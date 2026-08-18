import ReactMarkdown from "react-markdown";
import type { RunView } from "../lib/types";

export function ReviewPane({ view }: { view: RunView }) {
  if (!view.error && !view.review) return null;

  return (
    <div className="panel p-5">
      {view.error && <p className="text-sm text-err">Run failed: {view.error}</p>}
      {view.review && (
        <div>
          <p className="eyebrow mb-2">Verdict</p>
          <div className="markdown">
            <ReactMarkdown>{view.review}</ReactMarkdown>
          </div>
        </div>
      )}
    </div>
  );
}
