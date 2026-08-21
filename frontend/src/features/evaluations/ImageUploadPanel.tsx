import { ChangeEvent, useState } from "react";
import type { SuiteCase } from "../../types/evaluations";

export interface ImageUploadEntry {
  case_id: string;
  data_url: string;
  name: string;
  media_type: string;
}

const MAX_IMAGE_BYTES = 10 * 1024 * 1024;
const ACCEPTED_MEDIA = [
  "image/jpeg",
  "image/png",
  "image/webp",
  "image/heic",
  "image/he",
  "image/heif",
  "image/heix",
  "image/gif",
];

interface ImageUploadPanelProps {
  cases: SuiteCase[];
  entries: Record<string, ImageUploadEntry>;
  onChange(case_id: string, entry: ImageUploadEntry | null): void;
}

function formatSize(bytes: number): string {
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  const kibi = bytes / 1024;
  if (kibi < 1024) {
    return `${kibi.toFixed(0)} KiB`;
  }
  return `${(kibi / 1024).toFixed(1)} MiB`;
}

function readFile(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.addEventListener("load", () => resolve(reader.result as string));
    reader.addEventListener("error", () => reject(reader.error ?? new Error("file read failed")));
    reader.readAsDataURL(file);
  });
}

function caseLabel(case_type: string | null): string {
  if (case_type === "transcribe") {
    return "Exact transcription";
  }
  if (case_type === "interpret") {
    return "Inferred interpretation";
  }
  return "Image";
}

export function ImageUploadPanel({ cases, entries, onChange }: ImageUploadPanelProps) {
  const [error, setError] = useState<string | null>(null);

  const imageCases = cases.filter((case_item) => case_item.input_type === "image");
  if (imageCases.length === 0) {
    return null;
  }
  const uploadCases = imageCases.filter((case_item) => !case_item.has_fixture);

  const onFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const caseId = event.currentTarget.dataset.caseId as string;
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) {
      return;
    }
    setError(null);
    if (file.size > MAX_IMAGE_BYTES) {
      setError(`The file is too large (${formatSize(file.size)}). The maximum is ${formatSize(MAX_IMAGE_BYTES)}.`);
      onChange(caseId, null);
      return;
    }
    if (!ACCEPTED_MEDIA.includes(file.type) && file.type !== "") {
      setError(`This file type (${file.type || "unknown"}) is not supported. Choose a JPEG, PNG, WebP, HEIC/HEIF, or GIF image.`);
      onChange(caseId, null);
      return;
    }
    try {
      const data_url = await readFile(file);
      onChange(caseId, { case_id: caseId, data_url, name: file.name, media_type: file.type || "image/jpeg" });
      setError(null);
    } catch {
      setError("The file could not be read.");
      onChange(caseId, null);
    }
  };

  const onRemove = (caseId: string) => {
    onChange(caseId, null);
    setError(null);
  };

  const uploadedCount = uploadCases.filter((case_item) => entries[case_item.id]).length;

  return (
    <section className="eval-image-upload" data-testid="image-upload-panel">
      <h3>Upload images</h3>
      <p className="detail">
        Add an image to every case below. The board validates each file and converts it to JPEG before sending it to the model.
        {uploadCases.length === 0 ? null : uploadedCount === uploadCases.length ? uploadCases.length === 1 ? " (1 uploaded)" : ` (${uploadedCount} uploaded)` : null}
        {uploadCases.length > 0 && uploadedCount < uploadCases.length ? ` · ${uploadCases.length - uploadedCount} still needed` : null}
      </p>
      {error ? (
        <p className="status error" data-testid="image-upload-error">
          {error}
        </p>
      ) : null}

      {imageCases.map((case_item, position) => {
        const entry = entries[case_item.id];
        return (
          <div className="image-upload-item" key={case_item.id} data-testid={`image-upload-${case_item.id}`}>
            <div className="image-upload-header">
              <span className="image-upload-index">Case {position + 1}</span>
              <span className="image-upload-badge">{caseLabel(case_item.case_type)}</span>
            </div>
            {case_item.category ? (
              <span className="image-upload-category">{case_item.category}</span>
            ) : null}
            <p className="image-upload-prompt">{case_item.prompt}</p>

            {case_item.has_fixture ? (
              <div className="image-upload-fixture" data-testid={`image-fixture-${case_item.id}`}>
                <span>Suite fixture</span>
                {case_item.expected_transcription != null ? (
                  <p className="image-upload-expected-transcription">
                    Expected transcription:{" "}
                    <code>{case_item.expected_transcription}</code>
                  </p>
                ) : null}
              </div>
            ) : entry ? (
              <div className="image-upload-preview" data-testid={`image-upload-preview-${case_item.id}`}>
                <img src={entry.data_url} alt={case_item.category ?? "uploaded image"} />
                <span className="image-upload-name">{entry.name}</span>
                <button
                  type="button"
                  className="image-upload-remove"
                  data-testid={`image-upload-remove-${case_item.id}`}
                  onClick={() => onRemove(case_item.id)}
                >
                  Remove
                </button>
              </div>
            ) : (
              <label>
                <input
                  type="file"
                  accept={ACCEPTED_MEDIA.join(",")}
                  data-case-id={case_item.id}
                  onChange={onFile}
                  data-testid={`image-upload-input-${case_item.id}`}
                  disabled={false}
                />
              </label>
            )}
          </div>
        );
      })}
    </section>
  );
}
