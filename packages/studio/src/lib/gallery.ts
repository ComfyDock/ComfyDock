import { contractTitle, outputKind } from "@/lib/format";
import type {
  ContractsResponse,
  GalleryItem,
  GalleryPhoto,
  RunOutputSlot,
  RunResponse,
} from "@/types";

type SelectedContract = NonNullable<ContractsResponse["contracts"][number]>;

export function galleryPhoto(item: GalleryItem): GalleryPhoto {
  return {
    src: item.url || "",
    width: Math.max(1, item.width || 1),
    height: Math.max(1, item.height || 1),
    key: item.id,
    item,
  };
}

export function galleryItemsFromOutputs(
  result: RunResponse,
  selected: SelectedContract,
  displayInputs: Record<string, unknown>,
) {
  const nextItems: GalleryItem[] = [];
  for (const output of result.outputs || []) {
    for (const artifact of output.artifacts || []) {
      const type = outputKind(output, artifact);
      nextItems.push({
        id: `${result.prompt_id || Date.now()}-${output.name}-${artifact.filename || nextItems.length}`,
        contract: contractTitle(selected),
        contractWorkflow: selected.workflow,
        contractName: selected.contract,
        promptId: result.prompt_id,
        output,
        artifact,
        filename: artifact.filename,
        outputName: output.name,
        type,
        url: artifact.url,
        status: "done",
        width: mediaWidth(type, artifact.width),
        height: mediaHeight(type, artifact.height),
        inputs: displayInputs,
        rawResult: result,
        createdAt: new Date().toISOString(),
      });
    }
  }
  return nextItems;
}

export function galleryItemsFromSlots(
  slots: RunOutputSlot[],
  selected: SelectedContract,
  displayInputs: Record<string, unknown>,
) {
  return slots.map((slot) => {
    const type = slot.type || "json";
    return {
      id: `gallery_${slot.slot_id}`,
      run_id: slot.run_id,
      slotId: slot.slot_id,
      contract: contractTitle(selected),
      contractWorkflow: selected.workflow,
      contractName: selected.contract,
      promptId: slot.promptId,
      outputName: slot.outputName,
      type,
      status: galleryStatusForSlot(slot.status),
      width: mediaWidth(type, slot.width),
      height: mediaHeight(type, slot.height),
      inputs: displayInputs,
      rawResult: slot.rawResult,
      error: slot.error,
      createdAt: slot.createdAt || new Date().toISOString(),
    } satisfies GalleryItem;
  });
}

export function pendingGalleryItemsFromContract(
  result: RunResponse,
  selected: SelectedContract,
  displayInputs: Record<string, unknown>,
) {
  const runId = result.run_id || result.id;
  if (!runId) return [];
  const createdAt = new Date().toISOString();
  return selected.outputs.map((output, index) => {
    const declaredType = String(output.type || "").toLowerCase();
    const type: GalleryItem["type"] =
      declaredType === "image" || declaredType === "video" || declaredType === "audio"
        ? declaredType
        : "json";
    return {
      id: `gallery_${runId}_${index}_${output.name}`,
      run_id: runId,
      contract: contractTitle(selected),
      contractWorkflow: selected.workflow,
      contractName: selected.contract,
      promptId: result.prompt_id,
      outputName: output.name,
      type,
      status: "pending",
      width: mediaWidth(type, undefined),
      height: mediaHeight(type, undefined),
      inputs: displayInputs,
      rawResult: result,
      createdAt,
    } satisfies GalleryItem;
  });
}

export function visibleGalleryItems(items: GalleryItem[]) {
  return items.filter((item) => item.status !== "cancelled" && (item.status !== "error" || item.error));
}

export function mergeGalleryItems(nextItems: GalleryItem[], currentItems: GalleryItem[]) {
  const nextIds = new Set(nextItems.map((item) => item.id));
  return [...nextItems, ...currentItems.filter((item) => !nextIds.has(item.id))];
}

export function appendGalleryItems(currentItems: GalleryItem[], nextItems: GalleryItem[]) {
  const currentIds = new Set(currentItems.map((item) => item.id));
  return [...currentItems, ...nextItems.filter((item) => !currentIds.has(item.id))];
}

export function normalizeGalleryItems(items: GalleryItem[]) {
  return items.filter((item) => item.status !== "cancelled").map(normalizeGalleryItem);
}

export function reconcileGalleryItems(nextItems: GalleryItem[], currentItems: GalleryItem[]) {
  const previousById = new Map(currentItems.map((item) => [item.id, item]));
  const reconciled = nextItems.filter((item) => item.status !== "cancelled").map((item) => {
    const normalized = normalizeGalleryItem(item);
    const previous = previousById.get(normalized.id);
    return previous && galleryItemRenderSignature(previous) === galleryItemRenderSignature(normalized) ? previous : normalized;
  });

  if (reconciled.length === currentItems.length && reconciled.every((item, index) => item === currentItems[index])) {
    return currentItems;
  }
  return reconciled;
}

export function removeRunPendingItems(items: GalleryItem[], runId: string) {
  return items.filter((item) => item.run_id !== runId || item.status !== "pending");
}

export function columnCountForWidth(width: number) {
  if (width < 620) return 2;
  if (width < 980) return 3;
  if (width < 1400) return 4;
  if (width < 1900) return 5;
  return 6;
}

function normalizeGalleryItem(item: GalleryItem) {
  const snakeItem = item as GalleryItem & {
    run_id?: string;
    slot_id?: string;
    contract_slug?: string;
    output_name?: string;
    prompt_id?: string;
    created_at?: string;
    updated_at?: string;
  };
  const artifact = item.artifact as
    | (GalleryItem["artifact"] & { download_url?: string; media_type?: string })
    | undefined;
  return {
    ...item,
    run_id: item.run_id || snakeItem.run_id,
    slotId: item.slotId || snakeItem.slot_id,
    contract: item.contract || snakeItem.contract_slug || "Contract",
    contractName: item.contractName || snakeItem.contract_slug,
    promptId: item.promptId || snakeItem.prompt_id,
    outputName: item.outputName || snakeItem.output_name,
    url: item.url || artifact?.download_url || artifact?.url,
    type: item.type || mediaTypeToOutputType(artifact?.media_type),
    status: normalizeGalleryStatus(item.status),
    width: Math.max(1, Number(item.width || 1)),
    height: Math.max(1, Number(item.height || 1)),
    createdAt: item.createdAt || snakeItem.created_at || new Date().toISOString(),
  };
}

function mediaTypeToOutputType(mediaType: string | undefined): GalleryItem["type"] | undefined {
  if (!mediaType) return undefined;
  if (mediaType.startsWith("image/")) return "image";
  if (mediaType.startsWith("video/")) return "video";
  if (mediaType.startsWith("audio/")) return "audio";
  return undefined;
}

function normalizeGalleryStatus(status: GalleryItem["status"] | string): GalleryItem["status"] {
  if (status === "completed") return "done";
  if (status === "queued" || status === "submitted" || status === "running") return "pending";
  if (status === "failed") return "error";
  if (status === "done" || status === "pending" || status === "error" || status === "cancelled") return status;
  return "pending";
}

function galleryStatusForSlot(status: RunOutputSlot["status"]): GalleryItem["status"] {
  if (status === "done") return "done";
  if (status === "error") return "error";
  if (status === "cancelled") return "cancelled";
  return "pending";
}

function mediaWidth(type: GalleryItem["type"], width: unknown) {
  if (type === "audio") return 4;
  if (type === "image" || type === "video") return Math.max(1, Number(width || 1));
  return 1;
}

function mediaHeight(type: GalleryItem["type"], height: unknown) {
  if (type === "audio") return 1;
  if (type === "image" || type === "video") return Math.max(1, Number(height || 1));
  return 1;
}

function galleryItemRenderSignature(item: GalleryItem) {
  return [
    item.id,
    item.run_id || "",
    item.slotId || "",
    item.status,
    item.type,
    item.url || "",
    item.filename || "",
    item.outputName || "",
    item.error || "",
    item.width,
    item.height,
    item.createdAt,
    item.contract,
    item.contractWorkflow || "",
    item.contractName || "",
    item.promptId || "",
  ].join("\u001f");
}
