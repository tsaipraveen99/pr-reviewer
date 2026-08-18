import { describe, expect, it } from "vitest";
import { reviewResultToEvents } from "./api";

describe("reviewResultToEvents", () => {
  it("translates a done status with a result to review_complete then done", () => {
    const events = reviewResultToEvents("done", { review: "## R", verified: [] });
    expect(events).toEqual([
      { type: "review_complete", review: "## R" },
      { type: "done" },
    ]);
  });

  it("translates a failed status to run_failed", () => {
    const events = reviewResultToEvents("failed", null);
    expect(events).toEqual([{ type: "run_failed", error: "run failed" }]);
  });

  it("translates a done status with no result to a connection-lost run_failed", () => {
    const events = reviewResultToEvents("done", null);
    expect(events).toEqual([{ type: "run_failed", error: "connection lost" }]);
  });

  it("translates an unexpected status (e.g. still running) to a connection-lost run_failed", () => {
    const events = reviewResultToEvents("running", null);
    expect(events).toEqual([{ type: "run_failed", error: "connection lost" }]);
  });
});
