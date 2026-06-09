import type { GalleryItem, OutputArtifact } from "@/types";

const DEFAULT_EXTENSION_BY_TYPE: Record<GalleryItem["type"], string> = {
  image: ".png",
  video: ".mp4",
  audio: ".wav",
  json: ".json",
};

const EXTENSION_BY_MEDIA_TYPE: Record<string, string> = {
  "image/jpeg": ".jpg",
  "image/jpg": ".jpg",
  "image/png": ".png",
  "image/webp": ".webp",
  "image/gif": ".gif",
  "video/mp4": ".mp4",
  "video/quicktime": ".mov",
  "video/webm": ".webm",
  "audio/mpeg": ".mp3",
  "audio/mp3": ".mp3",
  "audio/wav": ".wav",
  "audio/x-wav": ".wav",
  "audio/webm": ".webm",
  "application/json": ".json",
};

export function galleryItemDownloadFilename(item: GalleryItem) {
  const artifact = item.artifact;
  const explicitFilename = item.filename || artifactFilename(artifact);
  const baseName = explicitFilename || item.outputName || item.contractName || item.contract || "comfygit-output";
  const sanitized = sanitizeFilename(baseName);
  return ensureExtension(sanitized, extensionForItem(item));
}

export async function downloadGalleryItem(item: GalleryItem) {
  if (!item.url) return;

  const href = new URL(item.url, window.location.href).href;
  const filename = galleryItemDownloadFilename(item);

  try {
    const response = await fetch(href, { credentials: "include" });
    if (!response.ok) throw new Error(`Download failed with status ${response.status}`);
    const blob = await response.blob();
    const mediaType = item.artifact?.media_type || item.artifact?.content_type || mediaTypeForOutputType(item.type);
    const downloadBlob =
      blob.type || !mediaType ? blob : new Blob([await blob.arrayBuffer()], { type: mediaType });
    const objectUrl = URL.createObjectURL(downloadBlob);
    triggerDownload(objectUrl, filename);
    window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
  } catch {
    triggerDownload(href, filename);
  }
}

function artifactFilename(artifact: OutputArtifact | undefined) {
  return artifact?.filename || artifact?.storage_ref?.filename;
}

function extensionForItem(item: GalleryItem) {
  const mediaType = item.artifact?.media_type || item.artifact?.content_type;
  if (mediaType) {
    const extension = EXTENSION_BY_MEDIA_TYPE[mediaType.toLowerCase().split(";")[0].trim()];
    if (extension) return extension;
  }
  return DEFAULT_EXTENSION_BY_TYPE[item.type] || ".bin";
}

function mediaTypeForOutputType(type: GalleryItem["type"]) {
  if (type === "image") return "image/png";
  if (type === "video") return "video/mp4";
  if (type === "audio") return "audio/wav";
  if (type === "json") return "application/json";
  return "application/octet-stream";
}

function ensureExtension(filename: string, extension: string) {
  const cleanedExtension = extension.startsWith(".") ? extension : `.${extension}`;
  const lastSegment = filename.split("/").pop() || filename;
  if (/\.[a-z0-9]{2,8}$/i.test(lastSegment)) return filename;
  return `${filename}${cleanedExtension}`;
}

function sanitizeFilename(filename: string) {
  const sanitized = filename
    .replace(/[/\\?%*:|"<>]/g, "_")
    .replace(/[\x00-\x1f\x7f]/g, "")
    .trim();
  return sanitized && sanitized !== "." && sanitized !== ".." ? sanitized : "comfygit-output";
}

function triggerDownload(href: string, filename: string) {
  const link = document.createElement("a");
  link.href = href;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
}
