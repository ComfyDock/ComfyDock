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

export function visibleGalleryItems(items: GalleryItem[]) {
  return items.filter((item) => item.status !== "cancelled" && (item.status !== "error" || item.error));
}

export function mergeGalleryItems(nextItems: GalleryItem[], currentItems: GalleryItem[]) {
  const nextIds = new Set(nextItems.map((item) => item.id));
  return [...nextItems, ...currentItems.filter((item) => !nextIds.has(item.id))];
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
  return {
    ...item,
    width: Math.max(1, Number(item.width || 1)),
    height: Math.max(1, Number(item.height || 1)),
    createdAt: item.createdAt || new Date().toISOString(),
  };
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
