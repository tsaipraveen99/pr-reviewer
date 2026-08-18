import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { initialView } from "../lib/reducer";
import type { RunView } from "../lib/types";
import { ReviewPane } from "./ReviewPane";

const DONE_VIEW: RunView = { ...initialView(), review: "## R", done: true };

describe("ReviewPane", () => {
  let writeText: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
  });

  it("renders nothing when there is no review and no error", () => {
    const { container } = render(<ReviewPane view={initialView()} runId={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the Share button for a finished live run with a known runId", () => {
    render(<ReviewPane view={DONE_VIEW} runId="abc123" />);
    expect(screen.getByRole("button", { name: "Share" })).toBeInTheDocument();
  });

  it("hides the Share button when runId is unknown (showcase replay or permalink load)", () => {
    render(<ReviewPane view={DONE_VIEW} runId={null} />);
    expect(screen.queryByRole("button", { name: "Share" })).not.toBeInTheDocument();
  });

  it("hides the Share button while the run is still in progress", () => {
    render(<ReviewPane view={{ ...DONE_VIEW, done: false }} runId="abc123" />);
    expect(screen.queryByRole("button", { name: "Share" })).not.toBeInTheDocument();
  });

  it("copies the permalink and shows a transient Copied state on click", async () => {
    render(<ReviewPane view={DONE_VIEW} runId="abc123" />);
    fireEvent.click(screen.getByRole("button", { name: "Share" }));
    expect(await screen.findByRole("button", { name: "Copied ✓" })).toBeInTheDocument();
    expect(writeText).toHaveBeenCalledWith(`${location.origin}/#r=abc123`);
    expect(await screen.findByRole("button", { name: "Share" }, { timeout: 2000 })).toBeInTheDocument();
  });
});
