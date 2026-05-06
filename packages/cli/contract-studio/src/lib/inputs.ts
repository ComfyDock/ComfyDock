import { uploadInputFile } from "@/lib/api";
import type { ContractInput, ContractSummary, ImageInputValue } from "@/types";

export const inputDefaults = (contract: ContractSummary): Record<string, unknown> => {
  const values: Record<string, unknown> = {};
  for (const input of contract.inputs) {
    if (input.default !== undefined) {
      values[input.name] = input.default;
    } else if (input.type === "boolean") {
      values[input.name] = false;
    } else if (input.type === "image") {
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

export function imageInputFromFile(file: File): ImageInputValue {
  return {
    file,
    preview_url: URL.createObjectURL(file),
    filename: file.name || "image.png",
    mime_type: file.type || "image/png",
    size: file.size,
  };
}

export function imageInputValue(value: unknown): ImageInputValue | null {
  if (!value || typeof value !== "object") return null;
  const candidate = value as Partial<ImageInputValue>;
  if (!(candidate.file instanceof File) || typeof candidate.preview_url !== "string" || typeof candidate.filename !== "string") return null;
  return {
    file: candidate.file,
    preview_url: candidate.preview_url,
    filename: candidate.filename,
    mime_type: candidate.mime_type || "image/png",
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
    if (input.type === "image") {
      const imageValue = imageInputValue(value);
      submitInputs[input.name] = imageValue ? await uploadInputFile(imageValue) : value;
    } else {
      submitInputs[input.name] = value;
    }
  }
  return submitInputs;
}
