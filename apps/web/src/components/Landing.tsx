import type React from "react";

const APP_URL = "https://github.com/apps/pr-reviewer-crew-bot";
const GITHUB_URL: string =
  import.meta.env.VITE_GITHUB_URL ?? "https://github.com/tsaipraveen99/pr-reviewer";

// Programmatic scroll instead of bare hash links: the permalink hash format
// (#r=<id>) shares the fragment namespace, and re-clicking a link whose hash
// is already set is a no-op for native anchors. scrollIntoView always works.
function goTo(id: string) {
  return (e: React.MouseEvent) => {
    e.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: "smooth", block: "start" });
    history.replaceState(null, "", `#${id}`);
  };
}

export function TopNav() {
  return (
    <nav className="top-nav">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6">
        <a href="#top" onClick={goTo("top")} className="nav-wordmark">
          pr-reviewer
        </a>
        <div className="flex items-center gap-5">
          <a href="#github-app" onClick={goTo("github-app")} className="nav-link">
            GitHub App
          </a>
          <a href="#demo" onClick={goTo("demo")} className="nav-link">
            Live demo
          </a>
          <a href="#how" onClick={goTo("how")} className="nav-link nav-link-wide">
            How it works
          </a>
          <a href="#showcases" onClick={goTo("showcases")} className="nav-link nav-link-wide">
            Showcases
          </a>
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="nav-link">
            GitHub ↗
          </a>
        </div>
      </div>
    </nav>
  );
}

export function Hero() {
  return (
    <section id="github-app" className="pt-4">
      <p className="eyebrow">GitHub App</p>
      <h1 className="hero-title mt-2">
        Reviews that check what your PR <em>claims</em> against what it <em>does</em>.
      </h1>
      <p className="hero-sub mt-3">
        pr-reviewer installs on your repositories and reviews every pull request with
        whole-repo context from a code graph. An intent agent explores your codebase with
        real tools, then flags divergences between the description and the diff as inline
        comments on the exact changed lines.
      </p>
      <div className="mt-5 flex flex-wrap items-center gap-3">
        <a href={APP_URL} target="_blank" rel="noreferrer" className="mac-button inline-block">
          Install the GitHub App
        </a>
        <a href="#demo" onClick={goTo("demo")} className="mac-button-secondary inline-block">
          Try the live demo
        </a>
        <span className="text-xs text-secondary">Open source (MIT): self-host with your own GitHub App and Anthropic key.</span>
      </div>
    </section>
  );
}

export function WhatYouGet() {
  return (
    <section>
      <p className="eyebrow">What you get</p>
      <p className="mt-1 text-sm text-secondary">
        Real reviews from a staged test: one PR whose description promised validation and
        tests while the diff changed a help string, and one honest PR.
      </p>
      <div className="mt-4 grid gap-6 md:grid-cols-2">
        <figure className="shot-figure">
          <div className="shot-frame">
            <img
              src="/shots/inline-comment.png"
              alt="An inline pr-reviewer comment pinned to the changed diff line, labeled intent major"
              width={1202}
              height={760}
              loading="lazy"
            />
          </div>
          <figcaption className="shot-caption">
            Divergences land as inline comments on the changed line, with the evidence the
            agent dug up from your repo.
          </figcaption>
        </figure>
        <figure className="shot-figure">
          <div className="shot-frame">
            <img
              src="/shots/clean-pass.png"
              alt="A pr-reviewer review of an honest pull request: intent check reports the change matches its description"
              width={1394}
              height={954}
              loading="lazy"
            />
          </div>
          <figcaption className="shot-caption">
            Honest PRs get a clean verdict and no noise. Catching overclaims without crying
            wolf is the whole point.
          </figcaption>
        </figure>
      </div>
      <div className="mt-5 flex flex-wrap gap-2">
        <span className="fact-chip">$0.02–0.07 per typical review</span>
        <span className="fact-chip">30–60 seconds end to end</span>
        <span className="fact-chip">Never blocks merges (neutral checks)</span>
        <span className="fact-chip">Skips drafts, size-capped, daily-capped</span>
      </div>
    </section>
  );
}

const STEPS = [
  {
    n: "1",
    title: "Install the app on your repos",
    body: "One click on GitHub, pick the repositories. No CI config, no YAML, no webhooks to set up — the app brings its own.",
    result: "Result: the bot is watching for pull requests.",
  },
  {
    n: "2",
    title: "Open a pull request as normal",
    body: "The bot clones your branch, indexes the repo into a code graph, and runs a crew of five agents: intent (with repo-exploration tools), correctness, tests, security, and an adversarial verifier.",
    result: "Result: a pending check appears, then completes in about a minute.",
  },
  {
    n: "3",
    title: "Read the verdict",
    body: "The review leads with the intent check, pins divergences to changed lines, collapses the full crew report, and ends with exactly what it cost.",
    result: "Result: you know whether the PR does what it says before you read the diff.",
  },
];

export function InstallSteps() {
  return (
    <section>
      <p className="eyebrow">Install in three steps</p>
      <div className="mt-4 grid gap-4 md:grid-cols-3">
        {STEPS.map((s) => (
          <div key={s.n} className="panel step-card">
            <div className="step-number">{s.n}</div>
            <h3 className="card-title mt-2">{s.title}</h3>
            <p className="mt-2 text-sm text-secondary">{s.body}</p>
            <p className="mt-3 text-xs step-result">{s.result}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

const PIPELINE = [
  {
    title: "Code graph",
    body: "A tree-sitter indexer stores every function, class, and call/import edge in Postgres, incrementally per push.",
  },
  {
    title: "Context slice",
    body: "Changed symbols plus their callers, callees, and importers ride along in every agent's prompt.",
  },
  {
    title: "Intent tool loop",
    body: "The intent agent queries graph neighbors, reads files, and greps the clone — read-only, capped, budgeted.",
  },
  {
    title: "Adversarial verifier",
    body: "A second model cross-examines every finding and rejects anything unsupported before it reaches your PR.",
  },
];

export function HowItWorks() {
  return (
    <section id="how">
      <p className="eyebrow">How it works</p>
      <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {PIPELINE.map((p) => (
          <div key={p.title} className="panel step-card">
            <h3 className="card-title">{p.title}</h3>
            <p className="mt-2 text-sm text-secondary">{p.body}</p>
          </div>
        ))}
      </div>
      <p className="mt-4 text-sm text-secondary">
        The full architecture, cost model, and reliability story live in the{" "}
        <a href={`${GITHUB_URL}#architecture`} target="_blank" rel="noreferrer" className="text-accent">
          project README
        </a>
        , and the{" "}
        <a
          href={`${GITHUB_URL}/blob/main/docs/SELF_HOSTING.md`}
          target="_blank"
          rel="noreferrer"
          className="text-accent"
        >
          self-hosting guide
        </a>{" "}
        gets you running on your own key and infrastructure.
      </p>
    </section>
  );
}
