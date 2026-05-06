import type { FileRef, ImageInputValue, UploadPrepareResponse } from "@/types";

export async function apiJson<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const message =
      typeof data?.message === "string"
        ? data.message
        : typeof data?.error === "string"
          ? data.error
          : response.statusText;
    throw new Error(message || "Request failed");
  }
  return data as T;
}

export async function uploadInputFile(value: ImageInputValue): Promise<FileRef> {
  const slot = await apiJson<UploadPrepareResponse>("/uploads/prepare", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      filename: value.filename,
      mime_type: value.mime_type,
      size: value.size,
    }),
  });
  const response = await fetch(slot.upload_url, {
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
