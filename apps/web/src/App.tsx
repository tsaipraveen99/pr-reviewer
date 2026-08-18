import { useEffect } from "react";
import { AgentBoard } from "./components/AgentBoard";
import { PRForm } from "./components/PRForm";
import { ReviewPane } from "./components/ReviewPane";
import { ShowcaseGallery } from "./components/ShowcaseGallery";
import { useReviewRun } from "./hooks/useReviewRun";

const GITHUB_URL: string = import.meta.env.VITE_GITHUB_URL ?? "https://github.com/tsaipraveen99/pr-reviewer";

function App() {
  const { view, running, start, replay, runId, prUrl, loadFromHash } = useReviewRun();

  // A `#r=<id>` hash is a shareable permalink to a finished run; load it
  // once on mount and rebuild the board from its stored events.
  useEffect(() => {
    const match = /^#r=(.+)$/.exec(location.hash);
    if (match) loadFromHash(match[1]);
  }, [loadFromHash]);

  return (
    <div className="app-shell">
      <div className="mx-auto flex max-w-5xl flex-col gap-10 px-6 py-12">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="page-title">pr-reviewer</h1>
            <p className="mt-1 text-sm text-secondary">
              A crew of specialist agents reviews your pull request, live, in the browser.
            </p>
          </div>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="header-link mt-1">
            GitHub
          </a>
        </header>

        <PRForm running={running} onSubmit={start} initialUrl={prUrl} />
        {/* The verdict sits directly under the form, above the board, so it's
            visible without scrolling past the specialist cards once a run
            completes. */}
        <ReviewPane view={view} runId={runId} />
        <AgentBoard view={view} />
        <ShowcaseGallery running={running} onReplay={replay} />
      </div>
    </div>
  );
}

export default App;
