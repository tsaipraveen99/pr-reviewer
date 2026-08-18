import { useEffect, useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../lib/api";

interface PRFormProps {
  running: boolean;
  onSubmit: (prUrl: string) => Promise<void>;
  /** Set after a permalink load resolves, to show the shared run's PR. */
  initialUrl?: string;
}

export function PRForm({ running, onSubmit, initialUrl }: PRFormProps) {
  const [prUrl, setPrUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

  // initialUrl typically arrives async (after the permalink fetch resolves),
  // so it can't just seed useState's initial value -- it must sync in.
  useEffect(() => {
    if (initialUrl !== undefined) setPrUrl(initialUrl);
  }, [initialUrl]);

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setError(null);
    try {
      await onSubmit(prUrl);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Something went wrong. Try again.");
    }
  };

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-2">
      <div className="flex gap-2">
        <input
          type="url"
          required
          placeholder="https://github.com/owner/repo/pull/123"
          value={prUrl}
          onChange={e => setPrUrl(e.target.value)}
          disabled={running}
          className="mac-input mono flex-1"
        />
        <button type="submit" disabled={running} className="mac-button">
          {running ? "Reviewing…" : "Review PR"}
        </button>
      </div>
      {error && <p className="text-sm text-err">{error}</p>}
    </form>
  );
}
