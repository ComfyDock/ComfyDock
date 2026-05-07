import { uploadInputFile } from "@/lib/api";
import type { ContractInput, ContractSummary, FileInputValue } from "@/types";

export const FILE_UPLOAD_INPUT_TYPES = new Set(["image", "audio", "video", "file"]);

export const inputDefaults = (contract: ContractSummary): Record<string, unknown> => {
  const values: Record<string, unknown> = {};
  for (const input of contract.inputs) {
    if (input.default !== undefined) {
      values[input.name] = input.default;
    } else if (input.type === "boolean") {
      values[input.name] = false;
    } else if (isFileUploadInput(input)) {
      values[input.name] = null;
    } else {
      values[input.name] = "";
    }
  }
  return values;
};

export function valueForSubmit(input: ContractInput, value: unknown) {
  if (input.type === "integer") {
    const parsed = Number.parseInt(String(value), 10);
    return Number.isFinite(parsed) ? parsed : value;
  }
  if (input.type === "number") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : value;
  }
  return value;
}

export function isFileUploadInput(input: ContractInput) {
  return FILE_UPLOAD_INPUT_TYPES.has(input.type);
}

export function fileInputFromFile(file: File): FileInputValue {
  return {
    file,
    preview_url: URL.createObjectURL(file),
    filename: file.name || "upload.bin",
    mime_type: file.type || "application/octet-stream",
    size: file.size,
  };
}

export function fileInputValue(value: unknown): FileInputValue | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<FileInputValue>;
  if (!(candidate.file instanceof File) || typeof candidate.preview_url !== "string" || typeof candidate.filename !== "string") return null;
  return {
    file: candidate.file,
    preview_url: candidate.preview_url,
    filename: candidate.filename,
    mime_type: candidate.mime_type || candidate.file.type || "application/octet-stream",
    size: candidate.size || candidate.file.size,
  };
}

export async function prepareSubmitInputs(
  contract: ContractSummary,
  values: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  const submitInputs: Record<string, unknown> = {};
  for (const input of contract.inputs) {
    const value = valueForSubmit(input, values[input.name]);
    if (isFileUploadInput(input)) {
      const fileValue = fileInputValue(value);
      submitInputs[input.name] = fileValue ? await uploadInputFile(fileValue) : value;
    } else {
      submitInputs[input.name] = value;
    }
  }
  return submitInputs;
}
