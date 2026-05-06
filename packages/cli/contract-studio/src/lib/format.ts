import type { ContractSummary, GalleryItem, GalleryPhoto, OutputArtifact, RunOutput } from "@/types";

const LARGE_STRING_LIMIT = 800;
const DATA_URL_PREFIX_PATTERN = /^data:[^,]*;base64,/i;

export function labelFor(item: { display_name?: string; name: string }) {
  return item.display_name || item.name.replace(/[_-]+/g, " ");
}

export function contractTitle(contract: ContractSummary) {
  return contract.display_name || `${contract.workflow} / ${contract.contract}`;
}

export function compactType(type: string) {
  return type.toUpperCase();
}

export function titleFromOutput(value?: string) {
  return (value || "Output").replace(/[_-]+/g, " ");
}

export function formatGeneratedAt(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

export function abbreviatedMiddle(value: string, head = 96, tail = 48) {
  if (value.length <= head + tail + 16) return value;
  return `${value.slice(0, head)}...${value.slice(-tail)}`;
}

export function displayString(value: string) {
  if (DATA_URL_PREFIX_PATTERN.test(value)) {
    const separatorIndex = value.indexOf(",");
    const prefix = value.slice(0, separatorIndex + 1);
    const payload = value.slice(separatorIndex + 1);
    return `${prefix}${abbreviatedMiddle(payload, 48, 32)} [base64 omitted, ${payload.length.toLocaleString()} chars]`;
  }
  if (value.length > LARGE_STRING_LIMIT) {
    return `${abbreviatedMiddle(value, 240, 120)} [truncated, ${value.length.toLocaleString()} chars]`;
  }
  return value;
}

export function valueForDisplay(value: unknown): unknown {
  if (typeof value === "string") return displayString(value);
  if (Array.isArray(value)) return value.map((item) => valueForDisplay(item));
  if (!value || typeof value !== "object") return value;

  const result: Record<string, unknown> = {};
  for (const [key, child] of Object.entries(value)) {
    result[key] = valueForDisplay(child);
  }
  return result;
}

export function jsonBlock(value: unknown) {
  return JSON.stringify(valueForDisplay(value ?? {}), null, 2);
}

export function displayInputsForGallery(inputs: Record<string, unknown>): Record<string, unknown> {
  return valueForDisplay(inputs) as Record<string, unknown>;
}

export function galleryPhoto(item: GalleryItem): GalleryPhoto {
  return {
    src: item.url || "",
    width: Math.max(1, item.width || 1),
    height: Math.max(1, item.height || 1),
    key: item.id,
    item,
  };
}

export function imageDimensions(inputs: Record<string, unknown>) {
  const width = Number(inputs.width ?? inputs.W ?? inputs.w ?? 1024);
  const height = Number(inputs.height ?? inputs.H ?? inputs.h ?? width);
  return {
    width: Number.isFinite(width) && width > 0 ? width : 1024,
    height: Number.isFinite(height) && height > 0 ? height : 1024,
  };
}

export function outputKind(output: RunOutput, artifact: OutputArtifact): GalleryItem["type"] {
  const filename = String(artifact.filename || "").toLowerCase();
  const type = String(output.type || artifact.type || "").toLowerCase();
  if (type === "video" || /\.(mp4|webm|mov|mkv)$/.test(filename)) return "video";
  if (type === "image" || /\.(png|jpe?g|webp|gif|bmp)$/.test(filename)) return "image";
  return "json";
}

export function formatElapsed(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}
