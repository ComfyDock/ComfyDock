import { useCallback, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
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
  RunResponse,
} from "@/types";

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
  const [now, setNow] = useState(Date.now());
  const galleryScrollRef = useRef<HTMLDivElement | null>(null);
  const galleryMetrics = useGalleryMetrics(galleryScrollRef);

  const loadGallery = useCallback(async () => {
    const nextGallery = await apiJson<GalleryResponse>("/gallery");
    setGallery(normalizeGalleryItems(nextGallery.items || []));
  }, []);

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    const hasPending = gallery.some((item) => item.status === "pending");
    if (!hasPending) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [gallery]);

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
    const pendingId = `pending-${selected.workflow}-${selected.contract}-${Date.now()}`;
    setGallery((current) => [
      {
        id: pendingId,
        contract: contractTitle(selected),
        contractWorkflow: selected.workflow,
        contractName: selected.contract,
        type: "image",
        status: "pending",
        width: 1,
        height: 1,
        inputs: displayInputs,
        createdAt: new Date().toISOString(),
      },
      ...current,
    ]);
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
        : galleryItemsFromOutputs(result, selected, displayInputs);
      if (nextItems.length) {
        setGallery((current) => [...nextItems, ...current.filter((item) => item.id !== pendingId)]);
      } else {
        setGallery((current) => current.filter((item) => item.id !== pendingId));
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
        setGallery((current) => [...errorItems, ...current.filter((item) => item.id !== pendingId)]);
        setStatus(message);
        return;
      }
      setStatus(message);
      setGallery((current) =>
        current.map((item) => (item.id === pendingId ? { ...item, status: "error", error: message } : item)),
      );
    } finally {
      setBusy(false);
    }
  }, [busy, inputs, selected]);

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
  const galleryLayout = useMemo(() => layoutGalleryItems(visibleGallery, galleryMetrics), [galleryMetrics, visibleGallery]);
  const activeItem = visibleGallery.find((item) => item.id === activeId) || null;
  const activeIndex = activeItem ? visibleGallery.findIndex((item) => item.id === activeItem.id) : -1;

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

        <div ref={galleryScrollRef} className="gallery-scroll">
          {visibleGallery.length ? (
            <section className="gallery" aria-label="Generated outputs" style={{ height: galleryLayout.height }}>
              {galleryLayout.tiles.map((tile) => (
                <div
                  className="gallery-tile-frame"
                  key={tile.item.id}
                  style={
                    {
                      width: tile.width,
                      height: tile.height,
                      transform: `translate3d(${tile.x}px, ${tile.y}px, 0)`,
                    } as CSSProperties
                  }
                >
                  <GalleryTile
                    item={tile.item}
                    fill
                    now={now}
                    onOpen={setActiveId}
                    onCopy={copyGalleryItem}
                    onDelete={deleteGalleryItem}
                  />
                </div>
              ))}
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

type GalleryMetrics = {
  width: number;
  columnCount: number;
};

function layoutGalleryItems(items: GalleryItem[], metrics: GalleryMetrics) {
  const gap = GALLERY_GAP_PX;
  const columnCount = Math.max(1, metrics.columnCount);
  const availableWidth = Math.max(280, metrics.width);
  const columnWidth = Math.max(120, (availableWidth - gap * (columnCount - 1)) / columnCount);
  const columnHeights = Array.from({ length: columnCount }, () => 0);
  const tiles = items.map((item, index) => {
    const columnIndex = index % columnCount;
    const x = columnIndex * (columnWidth + gap);
    const y = columnHeights[columnIndex];
    const height = tileHeightForWidth(item, columnWidth);
    columnHeights[columnIndex] += height + gap;
    return {
      item,
      x,
      y,
      width: columnWidth,
      height,
    };
  });
  return {
    tiles,
    height: Math.max(0, ...columnHeights) + 120,
  };
}

const GALLERY_GAP_PX = 7;
const AUDIO_TILE_HEIGHT_PX = 76;

function tileHeightForWidth(item: GalleryItem, width: number) {
  if (item.type === "audio") return AUDIO_TILE_HEIGHT_PX;
  const ratio = Math.max(0.1, Number(item.height || 1)) / Math.max(0.1, Number(item.width || 1));
  return Math.max(90, width * ratio);
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

function normalizeGalleryItems(items: GalleryItem[]) {
  return items.map((item) => ({
    ...item,
    width: Math.max(1, Number(item.width || 1)),
    height: Math.max(1, Number(item.height || 1)),
    createdAt: item.createdAt || new Date().toISOString(),
  }));
}

function runResponseFromUnknown(value: unknown): RunResponse | null {
  if (!value || typeof value !== "object") return null;
  return value as RunResponse;
}

function useGalleryMetrics(stageRef: React.RefObject<HTMLElement | null>) {
  const [metrics, setMetrics] = useState<GalleryMetrics>({ width: 1600, columnCount: 6 });

  useEffect(() => {
    const target = stageRef.current;
    if (!target) return;

    const update = () => {
      const width = Math.max(0, target.clientWidth - GALLERY_SCROLLBAR_GUTTER_PX);
      setMetrics({ width, columnCount: columnCountForWidth(width) });
    };
    update();

    const observer = new ResizeObserver(update);
    observer.observe(target);
    return () => observer.disconnect();
  }, [stageRef]);

  return metrics;
}

const GALLERY_SCROLLBAR_GUTTER_PX = 19;

function columnCountForWidth(width: number) {
  if (width < 620) return 2;
  if (width < 980) return 3;
  if (width < 1400) return 4;
  if (width < 1900) return 5;
  return 6;
}
