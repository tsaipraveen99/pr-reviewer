import type React from "react";

const APP_URL = "https://github.com/apps/pr-reviewer-crew-bot";
const GITHUB_URL: string =
  import.meta.env.VITE_GITHUB_URL ?? "https://github.com/tsaipraveen99/pr-reviewer";

// Programmatic, INSTANT scroll instead of bare hash links. Two reasons:
// the permalink format (#r=<id>) shares the fragment namespace and a
// re-click on an already-set hash is a native no-op; and Chromium cancels
// SMOOTH programmatic scrolls on any concurrent input or repaint jank,
// which reads as "the link did nothing". An instant jump cannot be
// cancelled.
function goTo(id: string) {
  return (e: React.MouseEvent) => {
    e.preventDefault();
    document.getElementById(id)?.scrollIntoView({ behavior: "auto", block: "start" });
    history.replaceState(null, "", `#${id}`);
  };
}

function InkWord({ children, delay = 0 }: { children: string; delay?: number }) {
  return (
    <span className="ink-word">
      <em>{children}</em>
      <svg
        className="ink-stroke"
        viewBox="0 0 100 12"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <path
          d="M2 8 C 20 4, 34 10, 52 7 S 84 4, 98 7"
          style={{ animationDelay: `${delay}s` }}
        />
      </svg>
    </span>
  );
}

export function TopNav() {
  return (
    <nav className="top-nav">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6">
        <a href="#top" onClick={goTo("top")} className="nav-wordmark">
          <svg className="nav-logo" viewBox="0 0 32 32" aria-hidden="true">
            <rect width="32" height="32" rx="7" fill="#18181b" />
            <circle cx="11" cy="11" r="3.5" fill="var(--accent)" />
            <circle cx="21" cy="11" r="3.5" fill="#e4e4e7" />
            <circle cx="11" cy="21" r="3.5" fill="#e4e4e7" />
            <circle cx="21" cy="21" r="3.5" fill="#e4e4e7" />
          </svg>
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
        Reviews that check what your PR <InkWord delay={0.4}>claims</InkWord> against
        what it <InkWord delay={0.9}>does</InkWord>.
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
      <div className="shot-stack mt-4 grid gap-6 md:grid-cols-2">
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
    result: "the bot is watching for pull requests",
  },
  {
    n: "2",
    title: "Open a pull request as normal",
    body: "The bot clones your branch, indexes the repo into a code graph, and runs a crew of five agents: intent (with repo-exploration tools), correctness, tests, security, and an adversarial verifier.",
    result: "a pending check appears, then completes in about a minute",
  },
  {
    n: "3",
    title: "Read the verdict",
    body: "The review leads with the intent check, pins divergences to changed lines, collapses the full crew report, and ends with exactly what it cost.",
    result: "you know whether the PR does what it says before you read the diff",
  },
];

export function InstallSteps() {
  return (
    <section>
      <p className="eyebrow">Install in three steps</p>
      <ol className="steps mt-6">
        {STEPS.map((s) => (
          <li key={s.n} className="step" data-reveal>
            <span className="step-ghost" aria-hidden="true">
              {s.n}
            </span>
            <div className="step-marker">{s.n}</div>
            <div className="step-body">
              <h3 className="step-title">{s.title}</h3>
              <p className="mt-1.5 text-sm text-secondary">{s.body}</p>
              <p className="step-result">
                <span aria-hidden="true">→</span> {s.result}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

const PIPELINE = [
  {
    title: "Code graph",
    body: "A tree-sitter indexer stores every function, class, and call/import edge in Postgres, incrementally per push.",
    snippet: "$ prgraph index .\n737 symbols \u00b7 4,352 edges",
  },
  {
    title: "Context slice",
    body: "Changed symbols plus their callers, callees, and importers ride along in every agent's prompt.",
    snippet: "[changed] report.monthly_total\n[caller]  cli.main",
  },
  {
    title: "Intent tool loop",
    body: "The intent agent queries graph neighbors, reads files, and greps the clone — read-only, capped, budgeted.",
    snippet: "\u2192 graph_neighbors(\"load_expenses\")\ncallers: total_by_category \u2026",
  },
  {
    title: "Adversarial verifier",
    body: "A second model cross-examines every finding and rejects anything unsupported before it reaches your PR.",
    snippet: "finding #3 \u2192 rejected\n\"evidence not in the diff\"",
  },
];

export function HowItWorks() {
  return (
    <section id="how">
      <p className="eyebrow">How it works</p>
      <div className="pipeline mt-6 grid gap-x-8 gap-y-8 sm:grid-cols-2 lg:grid-cols-4">
        {PIPELINE.map((p, i) => (
          <div key={p.title} className="pipeline-stage" data-reveal style={{ transitionDelay: `${i * 90}ms` }}>
            <p className="stage-index">{String(i + 1).padStart(2, "0")}</p>
            <h3 className="stage-title mt-2">{p.title}</h3>
            <p className="mt-1.5 text-sm text-secondary">{p.body}</p>
            <div className="stage-snippet">
              <pre>{p.snippet}</pre>
            </div>
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
