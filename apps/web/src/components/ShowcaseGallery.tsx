import { useEffect, useState } from "react";
import { fetchShowcases } from "../lib/api";
import type { ShowcaseSummary } from "../lib/api";

interface ShowcaseGalleryProps {
  running: boolean;
  onReplay: (slug: string) => void;
}

export function ShowcaseGallery({ running, onReplay }: ShowcaseGalleryProps) {
  const [showcases, setShowcases] = useState<ShowcaseSummary[]>([]);

  useEffect(() => {
    fetchShowcases()
      .then(setShowcases)
      .catch(() => setShowcases([]));
  }, []);

  if (showcases.length === 0) return null;

  return (
    <section className="flex flex-col gap-3">
      <h2 className="text-sm font-medium uppercase tracking-wide text-zinc-400">Showcases</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {showcases.map(sc => (
          <div key={sc.slug} className="flex flex-col gap-2 rounded-lg border border-zinc-800 bg-zinc-900/60 p-4">
            <h3 className="font-medium text-zinc-100">{sc.title}</h3>
            <p className="truncate text-xs text-zinc-500">{sc.pr_url}</p>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[11px] text-emerald-400">recorded run — zero cost</span>
              <button
                type="button"
                disabled={running}
                onClick={() => onReplay(sc.slug)}
                className="rounded-md border border-zinc-700 px-3 py-1 text-xs text-zinc-200 transition-colors hover:bg-zinc-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Replay
              </button>
            </div>
          </div>
        ))}
      </div>
    </section>
  );
}
