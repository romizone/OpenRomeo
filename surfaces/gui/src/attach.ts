import type { Attachment } from "./types";

export const MAX_BYTES = 10 * 1024 * 1024; // skip files larger than ~10MB
const TEXT_RE =
  /\.(txt|md|markdown|csv|tsv|json|ya?ml|log|ini|toml|py|js|ts|tsx|jsx|rs|go|java|c|h|cpp|sh|html?|css|sql|xml)$/i;
// Image files recognized by extension when the OS reports no MIME type (drag-drops of
// .webp/.svg on macOS sometimes arrive with an empty File.type).
const IMAGE_EXT_RE = /\.(png|jpe?g|gif|webp|svg|bmp|avif|heic|heif|tiff?)$/i;
// Office/OpenDocument uploads ride as base64 (`kind: "doc"`); the server extracts an
// inline text preview (doc_extract.py — extension-gated there too, keep both in sync).
// Legacy binary formats (.doc/.ppt/.xls) are converted server-side via LibreOffice.
const DOC_EXT_RE = /\.(docx|xlsx|xlsm|pptx|odt|ods|odp|doc|ppt|xls)$/i;

// Image types every provider takes as-is. Everything else (svg, webp, bmp, …) is
// rasterized to PNG at attach time: SVG is vision input nowhere, and WebP breaks on
// several OpenAI-compatible backends (Ollama, …) that only accept png/jpeg. Rasterizing
// in the webview needs no server-side image dependency, and the PNG that
// persist_attachments saves is also embeddable by the docx/pptx skills.
const IMAGE_PASSTHROUGH = new Set(["image/png", "image/jpeg", "image/gif"]);
const MAX_RASTER_DIM = 2048; // bound the PNG re-encode of big photos
const MAX_DATA_URL_CHARS = 12_000_000; // server's MAX_IMAGE_CHARS cap (attachments.py)

// Read a File into an Attachment (image/PDF → data URL, text → inline text). Returns null for
// unsupported types or oversized files. Shared by the composer and the session start panel.
export const isPdfFile = (file: File) =>
  file.type === "application/pdf" || /\.pdf$/i.test(file.name);

const loadImage = (src: string): Promise<HTMLImageElement> =>
  new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("decode failed"));
    img.src = src;
  });

// Decode via the webview and re-encode as PNG (JPEG fallback when the PNG re-encode of a
// large photo would blow the server's data-URL cap). Returns null when the webview cannot
// decode the file — the caller then falls back to sending the original bytes.
async function rasterizeToPng(
  file: File,
): Promise<{ data_url: string; ext: string; mime: string } | null> {
  const url = URL.createObjectURL(file);
  try {
    const img = await loadImage(url);
    // SVGs without width/height can report 0×0 — fall back to a readable default.
    let w = img.naturalWidth || 1024;
    let h = img.naturalHeight || 768;
    const scale = Math.min(1, MAX_RASTER_DIM / Math.max(w, h));
    w = Math.max(1, Math.round(w * scale));
    h = Math.max(1, Math.round(h * scale));
    const canvas = document.createElement("canvas");
    canvas.width = w;
    canvas.height = h;
    const ctx = canvas.getContext("2d");
    if (!ctx) return null;
    ctx.drawImage(img, 0, 0, w, h);
    const png = canvas.toDataURL("image/png");
    if (png.length <= MAX_DATA_URL_CHARS)
      return { data_url: png, ext: ".png", mime: "image/png" };
    // Photo-dense PNG over the cap → JPEG on white (drops alpha, keeps the upload alive).
    ctx.globalCompositeOperation = "destination-over";
    ctx.fillStyle = "#fff";
    ctx.fillRect(0, 0, w, h);
    const jpeg = canvas.toDataURL("image/jpeg", 0.85);
    return { data_url: jpeg, ext: ".jpg", mime: "image/jpeg" };
  } catch {
    return null;
  } finally {
    URL.revokeObjectURL(url);
  }
}

const readAsDataUrl = (file: File): Promise<string | null> =>
  new Promise((resolve) => {
    const reader = new FileReader();
    reader.onerror = () => resolve(null);
    reader.onload = () => resolve(String(reader.result));
    reader.readAsDataURL(file);
  });

const readAsText = (file: File): Promise<string | null> =>
  new Promise((resolve) => {
    const reader = new FileReader();
    reader.onerror = () => resolve(null);
    reader.onload = () => resolve(String(reader.result));
    reader.readAsText(file);
  });

export async function readFile(file: File): Promise<Attachment | null> {
  const isImage = file.type.startsWith("image/") || (!file.type && IMAGE_EXT_RE.test(file.name));
  const isPdf = isPdfFile(file);
  const isDoc = !isImage && !isPdf && DOC_EXT_RE.test(file.name);
  const isText =
    !isImage && !isPdf && !isDoc && (file.type.startsWith("text/") || TEXT_RE.test(file.name));
  if ((!isImage && !isPdf && !isDoc && !isText) || file.size > MAX_BYTES) return null;

  if (isImage) {
    const name = file.name || "image";
    if (!IMAGE_PASSTHROUGH.has(file.type)) {
      const raster = await rasterizeToPng(file);
      if (raster) {
        const base = name.replace(/\.[a-z0-9]+$/i, "") || "image";
        return { kind: "image", name: base + raster.ext, mime: raster.mime, data_url: raster.data_url };
      }
      // Undecodable in this webview — send the original bytes; the server-side
      // provider allowlists degrade it gracefully rather than failing the turn.
    }
    const url = await readAsDataUrl(file);
    return url ? { kind: "image", name, mime: file.type, data_url: url } : null;
  }
  if (isPdf) {
    const url = await readAsDataUrl(file);
    return url
      ? { kind: "pdf", name: file.name || "file.pdf", mime: "application/pdf", data_url: url }
      : null;
  }
  if (isDoc) {
    // The filename extension is what the server trusts (browser MIME for Office files is
    // unreliable, often application/octet-stream) — keep the original name intact.
    const url = await readAsDataUrl(file);
    return url
      ? {
          kind: "doc",
          name: file.name,
          mime: file.type || "application/octet-stream",
          data_url: url,
        }
      : null;
  }
  const text = await readAsText(file);
  return text !== null
    ? { kind: "text", name: file.name || "file.txt", mime: file.type, text }
    : null;
}
