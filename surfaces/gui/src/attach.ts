import type { Attachment } from "./types";

export const MAX_BYTES = 10 * 1024 * 1024; // skip files larger than ~10MB
const TEXT_RE =
  /\.(txt|md|markdown|csv|tsv|json|ya?ml|log|ini|toml|py|js|ts|tsx|jsx|rs|go|java|c|h|cpp|sh|html?|css|sql|xml)$/i;
// Office + OpenDocument: ride as data URLs like PDFs do. They are ZIP binaries, so reading
// them as text (the old fallback) produced garbage — before this they were dropped outright.
// The server saves the file and extracts its text locally (coworker/doc_extract.py).
const DOC_RE = /\.(docx|xlsx|xlsm|pptx|odt|ods|odp)$/i;

// Read a File into an Attachment (image/PDF/office → data URL, text → inline text). Returns
// null for unsupported types or oversized files. Shared by the composer and the session
// start panel.
export const isPdfFile = (file: File) =>
  file.type === "application/pdf" || /\.pdf$/i.test(file.name);

export const isDocFile = (file: File) => DOC_RE.test(file.name);

export function readFile(file: File): Promise<Attachment | null> {
  const isImage = file.type.startsWith("image/");
  const isPdf = isPdfFile(file);
  const isDoc = !isPdf && isDocFile(file);
  const isText = !isPdf && !isDoc && (file.type.startsWith("text/") || TEXT_RE.test(file.name));
  if ((!isImage && !isPdf && !isDoc && !isText) || file.size > MAX_BYTES) return Promise.resolve(null);
  return new Promise((resolve) => {
    const reader = new FileReader();
    reader.onerror = () => resolve(null);
    reader.onload = () =>
      resolve(
        isImage
          ? { kind: "image", name: file.name || "image", mime: file.type, data_url: String(reader.result) }
          : isPdf
            ? { kind: "pdf", name: file.name || "file.pdf", mime: "application/pdf", data_url: String(reader.result) }
            : isDoc
              ? {
                  kind: "doc",
                  // The server keys doc validation off the EXTENSION, so a nameless File
                  // (rare, but drag-and-drop from some apps) must not fall back to a bare
                  // "document" — that would be rejected server-side with no explanation.
                  name: file.name || `document${(DOC_RE.exec(file.name) || [".docx"])[0]}`,
                  mime: file.type,
                  data_url: String(reader.result),
                }
              : { kind: "text", name: file.name || "file.txt", mime: file.type, text: String(reader.result) },
      );
    if (isImage || isPdf || isDoc) reader.readAsDataURL(file);
    else reader.readAsText(file);
  });
}
