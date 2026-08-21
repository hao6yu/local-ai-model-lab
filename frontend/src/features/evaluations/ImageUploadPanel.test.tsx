import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SuiteCase } from "../../types/evaluations";
import { ImageUploadPanel, type ImageUploadEntry } from "./ImageUploadPanel";

function makeCase(case_id: string, input_type: "text" | "image", case_type: SuiteCase["case_type"] = null): SuiteCase {
  return {
    id: case_id,
    category: `Case ${case_id}`,
    prompt: `Do something with ${case_id}`,
    input_type,
    case_type,
    disabled: false,
    expected_transcription: null,
  };
}

function file(name = "photo.jpg", bytes = 1024, type = "image/jpeg"): File {
  return new File([new Uint8Array(bytes)], name, { type });
}

// A small controlled wrapper so the panel's uploads and removals flow through
// real parent state, exactly like EvaluationDashboard does.
function Harness({ cases, onReport }: { cases: SuiteCase[]; onReport: (case_id: string, entry: ImageUploadEntry | null) => void }) {
  const [entries, setEntries] = useState<Record<string, ImageUploadEntry>>({});
  return (
    <ImageUploadPanel
      cases={cases}
      entries={entries}
      onChange={(case_id, entry) => {
        onReport(case_id, entry);
        if (entry) {
          setEntries((prev) => ({ ...prev, [case_id]: entry }));
        } else {
          setEntries((prev) => {
            const next = { ...prev };
            delete next[case_id];
            return next;
          });
        }
      }}
    />
  );
}

const textCases: SuiteCase[] = [makeCase("T1", "text")];
const imageCases: SuiteCase[] = [
  makeCase("U1", "image", "transcribe"),
  makeCase("U2", "image", "interpret"),
];

describe("ImageUploadPanel", () => {
  const panelSpy = vi.fn<(case_id: string, entry: ImageUploadEntry | null) => void>();

  afterEach(() => {
    cleanup();
    panelSpy.mockClear();
  });

  it("renders nothing when the suite has no image cases", () => {
    render(<ImageUploadPanel cases={textCases} entries={{}} onChange={panelSpy} />);
    expect(screen.queryByTestId("image-upload-panel")).not.toBeInTheDocument();
  });

  it("renders an upload input for each image case", () => {
    render(<Harness cases={imageCases} onReport={panelSpy} />);
    expect(screen.getByTestId("image-upload-panel")).toBeInTheDocument();
    expect(screen.getByTestId("image-upload-input-U1")).toBeInTheDocument();
    expect(screen.getByTestId("image-upload-input-U2")).toBeInTheDocument();
  });

  it("reports each case-type label", () => {
    render(<Harness cases={imageCases} onReport={panelSpy} />);
    const panel = screen.getByTestId("image-upload-panel");
    expect(panel).toHaveTextContent("Exact transcription");
    expect(panel).toHaveTextContent("Inferred interpretation");
  });

  it("sends a data URL on upload", async () => {
    render(<Harness cases={imageCases} onReport={panelSpy} />);
    const input = screen.getByTestId("image-upload-input-U1") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file("first.jpg", 2048, "image/jpeg")] } });
    await screen.findByTestId("image-upload-preview-U1");
    const calls = panelSpy.mock.calls;
    expect(calls.length).toBeGreaterThan(0);
    const [, entry] = calls[calls.length - 1];
    expect(entry?.case_id).toBe("U1");
    expect(entry?.data_url).toMatch(/^data:image\/jpeg;base64,/);
    expect(entry?.media_type).toBe("image/jpeg");
  });

  it("shows an error and keeps the upload input for an oversized file", async () => {
    render(<Harness cases={imageCases} onReport={panelSpy} />);
    const input = screen.getByTestId("image-upload-input-U1") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file("huge.jpg", 10 * 1024 * 1024 + 1, "image/jpeg")] } });
    expect(await screen.findByTestId("image-upload-error")).toHaveTextContent("too large");
    expect(screen.getByTestId("image-upload-input-U1")).toBeInTheDocument();
  });

  it("shows an error for an unsupported media type", async () => {
    render(<Harness cases={imageCases} onReport={panelSpy} />);
    const input = screen.getByTestId("image-upload-input-U1") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file("notes.bin", 10, "application/octet-stream")] } });
    expect(await screen.findByTestId("image-upload-error")).toHaveTextContent("not supported");
    expect(screen.getByTestId("image-upload-input-U1")).toBeInTheDocument();
  });

  it("shows a preview and removes it on demand", async () => {
    render(<Harness cases={imageCases} onReport={panelSpy} />);
    const input = screen.getByTestId("image-upload-input-U1") as HTMLInputElement;
    fireEvent.change(input, { target: { files: [file("ok.jpg")] } });
    const preview = await screen.findByTestId("image-upload-preview-U1");
    expect(preview).toBeInTheDocument();
    expect(preview.querySelector("img")).toBeTruthy();
    fireEvent.click(screen.getByTestId("image-upload-remove-U1"));
    expect(await screen.findByTestId("image-upload-input-U1")).toBeInTheDocument();
    expect(screen.queryByTestId("image-upload-preview-U1")).not.toBeInTheDocument();
  });
});
