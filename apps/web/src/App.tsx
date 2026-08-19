import { useEffect } from "react";
import { AgentBoard } from "./components/AgentBoard";
import { Hero, HowItWorks, InstallSteps, TopNav, WhatYouGet } from "./components/Landing";
import { PRForm } from "./components/PRForm";
import { ReviewPane } from "./components/ReviewPane";
import { ShowcaseGallery } from "./components/ShowcaseGallery";
import { useReviewRun } from "./hooks/useReviewRun";

function App() {
  const { view, running, start, replay, runId, prUrl, loadFromHash } = useReviewRun();

  // A `#r=<id>` hash is a shareable permalink to a finished run; load it
  // once on mount and rebuild the board from its stored events.
  useEffect(() => {
    const match = /^#r=(.+)$/.exec(location.hash);
    if (match) loadFromHash(match[1]);
  }, [loadFromHash]);

  return (
    <div className="app-shell" id="top">
      <TopNav />
      <div className="mx-auto flex max-w-5xl flex-col gap-14 px-6 pb-16 pt-10">
        <Hero />
        <WhatYouGet />
        <InstallSteps />
        <HowItWorks />

        <section id="demo" className="flex flex-col gap-6">
          <div>
            <p className="eyebrow">Live demo</p>
            <p className="mt-1 text-sm text-secondary">
              Paste a public PR URL and watch the same crew review it, agent by agent, right
              here. Rate-limited; small PRs only.
            </p>
          </div>
          <PRForm running={running} onSubmit={start} initialUrl={prUrl} />
          {/* The verdict sits directly under the form, above the board, so it's
              visible without scrolling past the specialist cards once a run
              completes. */}
          <ReviewPane view={view} runId={runId} />
          <AgentBoard view={view} />
        </section>

        <section id="showcases">
          <ShowcaseGallery running={running} onReplay={replay} />
        </section>
      </div>
    </div>
  );
}

export default App;
