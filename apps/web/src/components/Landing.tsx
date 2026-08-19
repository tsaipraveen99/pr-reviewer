import type React from "react";
import { useEffect, useRef, useState } from "react";

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
    n: "01",
    title: "Install the app on your repos",
    body: "One click on GitHub, pick the repositories. No CI config, no YAML, no webhooks to set up — the app brings its own.",
  },
  {
    n: "02",
    title: "Open a pull request as normal",
    body: "The bot clones your branch, indexes the repo into a code graph, and runs a crew of five agents with whole-repo context.",
  },
  {
    n: "03",
    title: "Read the verdict",
    body: "Intent check first, divergences pinned to changed lines, the full crew report collapsed, and exactly what it cost.",
  },
];

const AGENTS = ["intent", "correctness", "tests", "security", "verifier"];

function useCountUp(target: number, active: boolean, ms = 900) {
  const [value, setValue] = useState(0);
  useEffect(() => {
    if (!active) return;
    if (matchMedia("(prefers-reduced-motion: reduce)").matches) {
      setValue(target);
      return;
    }
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      setValue(target * (1 - Math.pow(1 - k, 3)));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, active, ms]);
  return value;
}

function SimInstall() {
  return (
    <div className="sim-scene">
      <div className="sim-titlebar">
        <svg className="nav-logo" viewBox="0 0 32 32" aria-hidden="true">
          <rect width="32" height="32" rx="7" fill="#18181b" />
          <circle cx="11" cy="11" r="3.5" fill="var(--accent)" />
          <circle cx="21" cy="11" r="3.5" fill="#e4e4e7" />
          <circle cx="11" cy="21" r="3.5" fill="#e4e4e7" />
          <circle cx="21" cy="21" r="3.5" fill="#e4e4e7" />
        </svg>
        <span className="sim-strong">pr-reviewer</span>
        <span className="sim-install-btn">Install</span>
      </div>
      {["acme/api", "acme/web", "acme/infra"].map((repo, i) => (
        <div className="sim-repo" style={{ animationDelay: `${0.25 + i * 0.22}s` }} key={repo}>
          <span className="sim-check" style={{ animationDelay: `${0.45 + i * 0.22}s` }}>✓</span>
          <span className="mono">{repo}</span>
        </div>
      ))}
      <p className="sim-mono-line" style={{ animationDelay: "1.15s" }}>
        → watching 3 repositories
      </p>
    </div>
  );
}

function SimReview() {
  return (
    <div className="sim-scene">
      <div className="sim-prbar">
        <span className="sim-strong">Validate expense amounts</span>
        <span className="sim-branch mono">feat/amounts</span>
      </div>
      <div className="sim-checkrow">
        <span className="sim-pulse" />
        <span className="mono">pr-reviewer — in progress</span>
      </div>
      <div className="sim-agents">
        {AGENTS.map((a, i) => (
          <span className="sim-agent mono" style={{ animationDelay: `${0.3 + i * 0.5}s` }} key={a}>
            {a}
          </span>
        ))}
      </div>
    </div>
  );
}

function SimVerdict({ active }: { active: boolean }) {
  const cost = useCountUp(0.038, active);
  const tokens = useCountUp(10698, active);
  return (
    <div className="sim-scene">
      <p className="sim-verdict-title sim-type">Intent check: 1 divergence(s)</p>
      <div className="sim-finding" style={{ animationDelay: "1.15s" }}>
        <span className="badge badge-major">major · intent</span>
        <span className="sim-finding-text">
          claims validation + tests; diff changes a help string
        </span>
      </div>
      <p className="sim-mono-line" style={{ animationDelay: "1.7s" }}>
        cost: ${cost.toFixed(3)} · {Math.round(tokens).toLocaleString()} tokens
      </p>
      <p className="sim-mono-line sim-neutral" style={{ animationDelay: "2.1s" }}>
        ✓ neutral check — never blocks your merge
      </p>
    </div>
  );
}

export function InstallSteps() {
  const [active, setActive] = useState(0);
  const stepRefs = useRef<(HTMLLIElement | null)[]>([]);

  useEffect(() => {
    if (typeof IntersectionObserver === "undefined") return;
    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            setActive(Number((entry.target as HTMLElement).dataset.step));
          }
        }
      },
      { rootMargin: "-42% 0px -42% 0px" },
    );
    for (const el of stepRefs.current) {
      if (el) observer.observe(el);
    }
    return () => observer.disconnect();
  }, []);

  return (
    <section>
      <p className="eyebrow">Install in three steps</p>
      <div className="sim-layout mt-6">
        <ol className="sim-steps">
          {STEPS.map((s, i) => (
            <li
              key={s.n}
              data-step={i}
              ref={(el) => {
                stepRefs.current[i] = el;
              }}
              className={`sim-step${active === i ? " is-active" : ""}`}
            >
              <span className="sim-step-index">{s.n}</span>
              <h3 className="step-title">{s.title}</h3>
              <p className="mt-2 text-sm text-secondary">{s.body}</p>
            </li>
          ))}
        </ol>
        <div className="sim-stage-wrap">
          <div className="sim-stage panel" key={active}>
            {active === 0 && <SimInstall />}
            {active === 1 && <SimReview />}
            {active === 2 && <SimVerdict active />}
          </div>
        </div>
      </div>
    </section>
  );
}

const FLOW = [
  { title: "diff", snippet: "+42 −7 across 3 files" },
  { title: "code graph", snippet: "$ prgraph index .\n737 symbols · 4,352 edges" },
  { title: "context slice", snippet: "[changed] monthly_total\n[caller]  cli.main" },
  { title: "agent crew", snippet: "intent · tools ≤10 calls\n+ 3 specialists" },
  { title: "verifier", snippet: "finding #3 → rejected\n\"evidence not in diff\"" },
  { title: "review", snippet: "inline comments\ncost: $0.038" },
];

export function HowItWorks() {
  return (
    <section id="how">
      <p className="eyebrow">How it works</p>
      <div className="flow mt-8" data-reveal>
        <svg className="flow-line" viewBox="0 0 100 2" preserveAspectRatio="none" aria-hidden="true">
          <line x1="0" y1="1" x2="100" y2="1" className="flow-line-base" />
          <line x1="0" y1="1" x2="100" y2="1" className="flow-line-dash" />
        </svg>
        {FLOW.map((node, i) => (
          <div className="flow-node" key={node.title} style={{ animationDelay: `${i * 0.35}s` }}>
            <button type="button" className="flow-chip">
              <span className="stage-index">{String(i + 1).padStart(2, "0")}</span>
              {node.title}
            </button>
            <div className="flow-pop panel">
              <pre>{node.snippet}</pre>
            </div>
          </div>
        ))}
      </div>
      <p className="mt-6 text-sm text-secondary">
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
