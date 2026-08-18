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
      <h2 className="eyebrow">Showcases</h2>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {showcases.map(sc => (
          <div key={sc.slug} className="panel flex flex-col gap-2 p-4">
            <h3 className="card-title">{sc.title}</h3>
            <p className="truncate text-xs text-secondary">{sc.pr_url}</p>
            <div className="mt-1 flex items-center justify-between">
              <span className="text-[11px] text-ok">recorded run — zero cost</span>
              <button
                type="button"
                disabled={running}
                onClick={() => onReplay(sc.slug)}
                className="mac-button-secondary"
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
