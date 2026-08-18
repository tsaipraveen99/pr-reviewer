import { AgentBoard } from "./components/AgentBoard";
import { PRForm } from "./components/PRForm";
import { ReviewPane } from "./components/ReviewPane";
import { ShowcaseGallery } from "./components/ShowcaseGallery";
import { useReviewRun } from "./hooks/useReviewRun";

const GITHUB_URL: string = import.meta.env.VITE_GITHUB_URL ?? "https://github.com/tsaipraveen99/pr-reviewer";

function App() {
  const { view, running, start, replay } = useReviewRun();

  return (
    <div className="app-shell">
      <div className="window-wrap mx-auto max-w-5xl">
        <div className="panel window">
          <div className="titlebar">
            <div className="titlebar-dots" aria-hidden="true">
              <span className="traffic-dot traffic-dot-close" />
              <span className="traffic-dot traffic-dot-min" />
              <span className="traffic-dot traffic-dot-zoom" />
            </div>
            <span className="win-title">pr-reviewer</span>
            <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="win-link">
              GitHub
            </a>
          </div>
          <div className="hairline-b" />
          <div className="flex flex-col gap-10 px-6 py-6">
            <header>
              <h1 className="sr-only">pr-reviewer</h1>
              <p className="text-sm text-secondary">
                A crew of specialist agents reviews your pull request, live, in the browser.
              </p>
            </header>

            <PRForm running={running} onSubmit={start} />
            {/* The verdict sits directly under the form, above the board, so it's
                visible without scrolling past the specialist cards once a run
                completes. */}
            <ReviewPane view={view} />
            <AgentBoard view={view} />
            <ShowcaseGallery running={running} onReplay={replay} />
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
