import { AgentBoard } from "./components/AgentBoard";
import { PRForm } from "./components/PRForm";
import { ReviewPane } from "./components/ReviewPane";
import { ShowcaseGallery } from "./components/ShowcaseGallery";
import { useReviewRun } from "./hooks/useReviewRun";

function App() {
  const { view, running, start, replay } = useReviewRun();

  return (
    <div className="min-h-screen bg-zinc-950 text-zinc-100">
      <div className="mx-auto flex max-w-4xl flex-col gap-10 px-6 py-12">
        <header className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">pr-crew</h1>
            <p className="mt-1 text-sm text-zinc-400">
              A crew of specialist agents reviews your pull request, live, in the browser.
            </p>
          </div>
          <a
            href="https://github.com/"
            target="_blank"
            rel="noreferrer"
            className="mt-1 text-sm text-zinc-400 underline decoration-zinc-700 underline-offset-4 hover:text-zinc-100"
          >
            GitHub
          </a>
        </header>

        <PRForm running={running} onSubmit={start} />
        <AgentBoard view={view} />
        <ReviewPane view={view} />
        <ShowcaseGallery running={running} onReplay={replay} />
      </div>
    </div>
  );
}

export default App;
