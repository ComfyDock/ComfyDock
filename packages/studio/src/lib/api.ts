import type { FileInputValue, FileRef, UploadPrepareResponse } from "@/types";
import { studioApiPath } from "@/lib/runtime-config";

const SESSION_STORAGE_KEY = "comfygit_studio_session";

export class ApiError extends Error {
  status: number;
  data: unknown;

  constructor(message: string, status: number, data: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.data = data;
  }
}

export async function apiJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(studioApiPath(path), {
    ...options,
    headers: requestHeaders(options?.headers),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      typeof data?.message === "string"
        ? data.message
        : typeof data?.error === "string"
          ? data.error
          : response.statusText;
    throw new ApiError(message || "Request failed", response.status, data);
  }
  return data as T;
}

function requestHeaders(headers?: HeadersInit): Headers {
  const next = new Headers(headers);
  if (!next.has("x-comfygit-studio-session")) {
    next.set("x-comfygit-studio-session", studioSessionId());
  }
  return next;
}

function studioSessionId(): string {
  const existing = window.localStorage.getItem(SESSION_STORAGE_KEY);
  if (existing && /^[A-Za-z0-9_-]+$/.test(existing)) {
    return existing;
  }
  const generated = `anon_${randomId()}`;
  window.localStorage.setItem(SESSION_STORAGE_KEY, generated);
  return generated;
}

function randomId(): string {
  const randomUUID = globalThis.crypto?.randomUUID;
  if (typeof randomUUID === "function") {
    return randomUUID.call(globalThis.crypto).replaceAll("-", "");
  }
  const bytes = new Uint8Array(16);
  globalThis.crypto?.getRandomValues?.(bytes);
  const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  if (hex !== "0".repeat(32)) {
    return hex;
  }
  return `${Date.now().toString(36)}${Math.random().toString(36).slice(2)}`;
}

export async function uploadInputFile(value: FileInputValue): Promise<FileRef> {
  const slot = await apiJson<UploadPrepareResponse>("/uploads/prepare", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      filename: value.filename,
      mime_type: value.mime_type,
      size: value.size,
    }),
  });
  const response = await fetch(studioApiPath(slot.upload_url), {
    method: slot.method || "PUT",
    headers: slot.headers || { "content-type": value.mime_type },
    body: value.file,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      typeof data?.message === "string"
        ? data.message
        : typeof data?.error === "string"
          ? data.error
          : response.statusText;
    throw new Error(message || "Upload failed");
  }
  return (data.file_ref || slot.file_ref) as FileRef;
}
