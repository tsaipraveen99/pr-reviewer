import { useState } from "react";
import type { FormEvent } from "react";
import { ApiError } from "../lib/api";

interface PRFormProps {
  running: boolean;
  onSubmit: (prUrl: string) => Promise<void>;
}

export function PRForm({ running, onSubmit }: PRFormProps) {
  const [prUrl, setPrUrl] = useState("");
  const [error, setError] = useState<string | null>(null);

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
          className="flex-1 rounded-md border border-zinc-700 bg-zinc-900 px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={running}
          className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-zinc-700 disabled:text-zinc-400"
        >
          {running ? "Reviewing…" : "Review PR"}
        </button>
      </div>
      {error && <p className="text-sm text-red-400">{error}</p>}
    </form>
  );
}
