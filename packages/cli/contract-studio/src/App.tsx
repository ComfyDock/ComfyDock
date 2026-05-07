import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import { MasonryPhotoAlbum } from "react-photo-album";
import "react-photo-album/masonry.css";
import { Wand2 } from "lucide-react";
import { Field, StudioSelect } from "@/app/components";
import { ContractInputControl } from "@/components/ContractInputControl";
import { GalleryTile } from "@/components/GalleryTile";
import { OutputViewer } from "@/components/OutputViewer";
import { Button } from "@/components/ui/button";
import { ApiError, apiJson } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import {
  contractTitle,
  displayInputsForGallery,
  galleryPhoto,
  jsonBlock,
  outputKind,
} from "@/lib/format";
import { inputDefaults, prepareSubmitInputs } from "@/lib/inputs";
import type {
  ContractsResponse,
  GalleryDeleteResponse,
  GalleryItem,
  GalleryResponse,
  HealthResponse,
  RunIssue,
  RunOutputSlot,
  RunResponse,
} from "@/types";

const GALLERY_INITIAL_BATCH = 72;
const GALLERY_BATCH_SIZE = 48;
const GALLERY_SPACING_PX = 7;
const GALLERY_LOAD_MORE_THRESHOLD_PX = 900;

export function App() {
  const [contractsData, setContractsData] = useState<ContractsResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [, setStatus] = useState("Ready");
  const [issues, setIssues] = useState<RunIssue[]>([]);
  const [gallery, setGallery] = useState<GalleryItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [rawResult, setRawResult] = useState<RunResponse | null>(null);
  const [galleryRenderCount, setGalleryRenderCount] = useState(GALLERY_INITIAL_BATCH);
  const galleryScrollRef = useRef<HTMLDivElement | null>(null);

  const loadGallery = useCallback(async () => {
    const nextGallery = await apiJson<GalleryResponse>("/gallery");
    setGallery((current) => reconcileGalleryItems(nextGallery.items || [], current));
  }, []);

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    const hasPending = gallery.some((item) => item.status === "pending");
    if (!hasPending) return;
    const interval = window.setInterval(() => {
      void loadGallery();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [gallery, loadGallery]);

  const contracts = contractsData?.contracts || [];
  const selected = useMemo(
    () => contracts.find((item) => `${item.workflow}:${item.contract}` === selectedKey) || contracts[0],
    [contracts, selectedKey],
  );
  const activeKey = selected ? `${selected.workflow}:${selected.contract}` : "";

  useEffect(() => {
    if (!selected) return;
    setSelectedKey(`${selected.workflow}:${selected.contract}`);
    setInputs(inputDefaults(selected));
    setIssues([]);
    setRawResult(null);
  }, [selected?.workflow, selected?.contract]);

  const refresh = useCallback(async () => {
    setStatus("Loading contracts");
    try {
      const [nextContracts, nextHealth] = await Promise.all([
        apiJson<ContractsResponse>("/contracts"),
        apiJson<HealthResponse>("/health"),
      ]);
      setContractsData(nextContracts);
      setHealth(nextHealth);
      await loadGallery();
      setStatus("Ready");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not load contracts");
    }
  }, [loadGallery]);

  const runSelected = useCallback(async () => {
    if (!selected || busy) return;
    setBusy(true);
    setIssues([]);
    setRawResult(null);
    setStatus("Uploading inputs");
    let submitInputs: Record<string, unknown>;
    try {
      submitInputs = await prepareSubmitInputs(selected, inputs);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Input upload failed";
      setStatus(message);
      setBusy(false);
      return;
    }
    setStatus("Submitting");
    const displayInputs = displayInputsForGallery(submitInputs);
    try {
      const result = await apiJson<RunResponse>(
        `/contracts/${encodeURIComponent(selected.workflow)}/${encodeURIComponent(selected.contract)}/run`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ inputs: submitInputs }),
        },
      );
      setRawResult(result);
      setIssues(result.issues || []);
      const nextItems = result.gallery_items?.length
        ? normalizeGalleryItems(result.gallery_items)
        : result.output_slots?.length
          ? galleryItemsFromSlots(result.output_slots, selected, displayInputs)
        : galleryItemsFromOutputs(result, selected, displayInputs);
      if (nextItems.length) {
        setGallery((current) => mergeGalleryItems(nextItems, current));
      } else {
        void loadGallery();
      }
      setStatus(result.status === "completed" ? "Completed" : result.status);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Generation failed";
      const errorData = error instanceof ApiError ? runResponseFromUnknown(error.data) : null;
      if (errorData?.issues?.length) {
        setIssues(errorData.issues);
      }
      if (errorData?.gallery_items?.length) {
        setRawResult(errorData);
        const errorItems = normalizeGalleryItems(errorData.gallery_items);
        setGallery((current) => mergeGalleryItems(errorItems, current));
        setStatus(message);
        return;
      }
      setStatus(message);
      void loadGallery();
    } finally {
      setBusy(false);
    }
  }, [busy, inputs, loadGallery, selected]);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if (event.defaultPrevented || event.repeat || event.isComposing) return;
      if (!event.ctrlKey || event.key !== "Enter") return;
      event.preventDefault();
      void runSelected();
    }

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [runSelected]);

  const copyGalleryItem = useCallback(async (item: GalleryItem) => {
    if (!item.url) {
      await copyText(jsonBlock(item.artifact?.raw || item.artifact || item.inputs || {}));
      return;
    }
    if (item.type !== "image") {
      await copyText(new URL(item.url, window.location.href).href);
      return;
    }
    try {
      const response = await fetch(item.url);
      const blob = await response.blob();
      const type = blob.type || "image/png";
      await navigator.clipboard.write([new ClipboardItem({ [type]: blob })]);
    } catch {
      await copyText(new URL(item.url, window.location.href).href);
    }
  }, []);

  const deleteGalleryItem = useCallback((item: GalleryItem) => {
    setGallery((current) => current.filter((candidate) => candidate.id !== item.id));
    setActiveId((current) => (current === item.id ? null : current));
    if (!item.id.startsWith("pending-")) {
      void apiJson<GalleryDeleteResponse>(`/gallery/${encodeURIComponent(item.id)}`, { method: "DELETE" }).catch(() => {
        void refresh();
      });
    }
  }, [refresh]);

  const visibleGallery = useMemo(() => gallery.filter((item) => item.status !== "error" || item.error), [gallery]);
  const renderedGallery = useMemo(() => visibleGallery.slice(0, galleryRenderCount), [galleryRenderCount, visibleGallery]);
  const renderedPhotos = useMemo(() => renderedGallery.map(galleryPhoto), [renderedGallery]);
  const hasMoreGallery = renderedGallery.length < visibleGallery.length;
  const activeItem = visibleGallery.find((item) => item.id === activeId) || null;
  const activeIndex = activeItem ? visibleGallery.findIndex((item) => item.id === activeItem.id) : -1;

  useEffect(() => {
    setGalleryRenderCount((current) =>
      Math.min(Math.max(GALLERY_INITIAL_BATCH, current), Math.max(GALLERY_INITIAL_BATCH, visibleGallery.length)),
    );
  }, [visibleGallery.length]);

  const loadMoreGalleryItems = useCallback(() => {
    setGalleryRenderCount((current) => Math.min(current + GALLERY_BATCH_SIZE, visibleGallery.length));
  }, [visibleGallery.length]);

  const onGalleryScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      if (!hasMoreGallery) return;
      const target = event.currentTarget;
      const remaining = target.scrollHeight - target.scrollTop - target.clientHeight;
      if (remaining < GALLERY_LOAD_MORE_THRESHOLD_PX) {
        loadMoreGalleryItems();
      }
    },
    [hasMoreGallery, loadMoreGalleryItems],
  );

  function moveActive(delta: number) {
    if (activeIndex < 0 || !visibleGallery.length) return;
    const next = visibleGallery[(activeIndex + delta + visibleGallery.length) % visibleGallery.length];
    setActiveId(next.id);
  }

  return (
    <main className="studio-shell">
      <section className="gallery-stage" aria-label="Outputs">
        <header className="top-bar">
          <div>
            <p className="eyebrow">ComfyGit Studio</p>
            <h1>{contractsData?.environment || "Environment"}</h1>
          </div>
          <div className="health-pill" data-ready={health?.comfyui?.available || undefined}>
            <span>{health?.comfyui?.available ? "ComfyUI online" : "ComfyUI unavailable"}</span>
          </div>
        </header>

        <div ref={galleryScrollRef} className="gallery-scroll" onScroll={onGalleryScroll}>
          {visibleGallery.length ? (
            <section className="gallery" aria-label="Generated outputs">
              <MasonryPhotoAlbum
                photos={renderedPhotos}
                spacing={GALLERY_SPACING_PX}
                padding={0}
                columns={columnCountForWidth}
                render={{
                  photo: (_, { photo, width, height }) => (
                    <GalleryTile
                      key={photo.item.id}
                      item={photo.item}
                      width={width}
                      height={height}
                      onOpen={setActiveId}
                      onCopy={copyGalleryItem}
                      onDelete={deleteGalleryItem}
                    />
                  ),
                }}
              />
              {hasMoreGallery ? (
                <button className="gallery-load-more" type="button" onClick={loadMoreGalleryItems}>
                  Load more
                </button>
              ) : null}
            </section>
          ) : (
            <div className="empty-stage">
              <p>Run a contract to collect outputs here.</p>
            </div>
          )}
        </div>
      </section>

      <aside className="control-panel">
        <div className="brand-row">
          <div>
            <p className="eyebrow">Contract</p>
            <h2>{contracts.length} available</h2>
          </div>
          <Button type="button" variant="tertiary" size="sm" onClick={refresh} disabled={busy}>
            Refresh
          </Button>
        </div>

        {contracts.length ? (
          <section className="contract-picker" aria-label="Select contract">
            <Field label="Workflow contract">
              <StudioSelect
                value={activeKey}
                disabled={busy}
                onChange={setSelectedKey}
                options={contracts.map((contract) => {
                  const key = `${contract.workflow}:${contract.contract}`;
                  return { label: contractTitle(contract), value: key };
                })}
              />
            </Field>
            {selected?.description ? <p className="description">{selected.description}</p> : null}
          </section>
        ) : null}

        {selected ? (
          <section className="runner-card">
            <div className="input-stack">
              {selected.inputs.map((input) => (
                <ContractInputControl
                  key={input.name}
                  input={input}
                  value={inputs[input.name]}
                  onChange={(value) => setInputs((current) => ({ ...current, [input.name]: value }))}
                />
              ))}
            </div>

            {issues.length ? (
              <div className="issue-list">
                {issues.map((issue, index) => (
                  <p key={`${issue.code}-${index}`}>{issue.message}</p>
                ))}
              </div>
            ) : null}

            <Button
              type="button"
              className="generate-button"
              onClick={runSelected}
              disabled={busy}
              loading={busy}
              leadingIcon={Wand2}
            >
              {busy ? "Generating..." : "Generate"}
            </Button>
          </section>
        ) : (
          <section className="runner-card">
            <p>No contracts found in this environment.</p>
          </section>
        )}

        {rawResult && !visibleGallery.length ? (
          <section className="raw-card">
            <p className="eyebrow">Raw result</p>
            <pre>{JSON.stringify(rawResult, null, 2)}</pre>
          </section>
        ) : null}
      </aside>

      {activeItem ? (
        <OutputViewer
          item={activeItem}
          hasNeighbors={visibleGallery.length > 1}
          onClose={() => setActiveId(null)}
          onMove={moveActive}
          onCopy={copyGalleryItem}
          onDelete={deleteGalleryItem}
        />
      ) : null}
    </main>
  );
}

function galleryItemsFromOutputs(
  result: RunResponse,
  selected: NonNullable<ContractsResponse["contracts"][number]>,
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
        width: type === "audio" ? 4 : type === "image" || type === "video" ? Math.max(1, Number(artifact.width || 1)) : 1,
        height: type === "audio" ? 1 : type === "image" || type === "video" ? Math.max(1, Number(artifact.height || 1)) : 1,
        inputs: displayInputs,
        rawResult: result,
        createdAt: new Date().toISOString(),
      });
    }
  }
  return nextItems;
}

function galleryItemsFromSlots(
  slots: RunOutputSlot[],
  selected: NonNullable<ContractsResponse["contracts"][number]>,
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
      status: slot.status === "error" ? "error" : "pending",
      width: type === "audio" ? 4 : Math.max(1, Number(slot.width || 1)),
      height: type === "audio" ? 1 : Math.max(1, Number(slot.height || 1)),
      inputs: displayInputs,
      rawResult: slot.rawResult,
      error: slot.error,
      createdAt: slot.createdAt || new Date().toISOString(),
    } satisfies GalleryItem;
  });
}

function mergeGalleryItems(nextItems: GalleryItem[], currentItems: GalleryItem[]) {
  const nextIds = new Set(nextItems.map((item) => item.id));
  return [...nextItems, ...currentItems.filter((item) => !nextIds.has(item.id))];
}

function normalizeGalleryItems(items: GalleryItem[]) {
  return items.map(normalizeGalleryItem);
}

function normalizeGalleryItem(item: GalleryItem) {
  return {
    ...item,
    width: Math.max(1, Number(item.width || 1)),
    height: Math.max(1, Number(item.height || 1)),
    createdAt: item.createdAt || new Date().toISOString(),
  };
}

function reconcileGalleryItems(nextItems: GalleryItem[], currentItems: GalleryItem[]) {
  const previousById = new Map(currentItems.map((item) => [item.id, item]));
  const reconciled = nextItems.map((item) => {
    const normalized = normalizeGalleryItem(item);
    const previous = previousById.get(normalized.id);
    return previous && galleryItemRenderSignature(previous) === galleryItemRenderSignature(normalized) ? previous : normalized;
  });

  if (reconciled.length === currentItems.length && reconciled.every((item, index) => item === currentItems[index])) {
    return currentItems;
  }
  return reconciled;
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

function runResponseFromUnknown(value: unknown): RunResponse | null {
  if (!value || typeof value !== "object") return null;
  return value as RunResponse;
}

function columnCountForWidth(width: number) {
  if (width < 620) return 2;
  if (width < 980) return 3;
  if (width < 1400) return 4;
  if (width < 1900) return 5;
  return 6;
}
