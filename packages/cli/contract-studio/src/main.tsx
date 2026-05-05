import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { MasonryPhotoAlbum } from "react-photo-album";
import "react-photo-album/masonry.css";
import { ChevronLeft, ChevronRight, Copy, Download, RotateCcw, Trash2, Wand2, X, ZoomIn, ZoomOut } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Field, Media, NumberPicker, StudioSelect, Tip } from "@/app/components";
import { ShapeProvider } from "@/lib/shape-context";
import { cn } from "@/lib/utils";
import "./styles.css";

type ContractInput = {
  name: string;
  type: string;
  required?: boolean;
  display_name?: string;
  default?: string | number | boolean | null;
  min?: number;
  max?: number;
  enum_values?: string[];
  description?: string;
};

type ContractOutput = {
  name: string;
  type: string;
  display_name?: string;
  description?: string;
};

type ContractSummary = {
  workflow: string;
  contract: string;
  display_name?: string;
  description?: string;
  inputs: ContractInput[];
  outputs: ContractOutput[];
};

type ContractsResponse = {
  environment: string;
  contracts: ContractSummary[];
};

type HealthResponse = {
  ok: boolean;
  environment: string;
  comfy_url: string;
  comfyui?: { available: boolean; error?: string };
};

type RunIssue = {
  code: string;
  message: string;
  severity?: string;
  input_name?: string;
};

type OutputArtifact = {
  filename?: string;
  subfolder?: string;
  type?: string;
  url?: string;
  raw?: unknown;
};

type RunOutput = {
  name: string;
  type: string;
  node_id: string;
  artifacts: OutputArtifact[];
};

type RunResponse = {
  status: string;
  prompt_id?: string;
  issues?: RunIssue[];
  outputs?: RunOutput[];
  error?: string;
  message?: string;
};

type GalleryItem = {
  id: string;
  contract: string;
  promptId?: string;
  output?: RunOutput;
  artifact?: OutputArtifact;
  filename?: string;
  outputName?: string;
  type: "image" | "video" | "json";
  url?: string;
  status: "pending" | "done" | "error";
  width: number;
  height: number;
  inputs?: Record<string, unknown>;
  error?: string;
  createdAt: string;
};

type GalleryPhoto = {
  src: string;
  width: number;
  height: number;
  key: string;
  item: GalleryItem;
};

const inputDefaults = (contract: ContractSummary): Record<string, unknown> => {
  const values: Record<string, unknown> = {};
  for (const input of contract.inputs) {
    if (input.default !== undefined) {
      values[input.name] = input.default;
    } else if (input.type === "boolean") {
      values[input.name] = false;
    } else {
      values[input.name] = "";
    }
  }
  return values;
};

async function apiJson<T>(path: string, options?: RequestInit): Promise<T> {
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

function labelFor(item: { display_name?: string; name: string }) {
  return item.display_name || item.name.replace(/[_-]+/g, " ");
}

function contractTitle(contract: ContractSummary) {
  return contract.display_name || `${contract.workflow} / ${contract.contract}`;
}

function compactType(type: string) {
  return type.toUpperCase();
}

function titleFromOutput(value?: string) {
  return (value || "Output").replace(/[_-]+/g, " ");
}

function galleryPhoto(item: GalleryItem): GalleryPhoto {
  return {
    src: item.url || "",
    width: Math.max(1, item.width || 1),
    height: Math.max(1, item.height || 1),
    key: item.id,
    item,
  };
}

function imageDimensions(inputs: Record<string, unknown>) {
  const width = Number(inputs.width ?? inputs.W ?? inputs.w ?? 1024);
  const height = Number(inputs.height ?? inputs.H ?? inputs.h ?? width);
  return {
    width: Number.isFinite(width) && width > 0 ? width : 1024,
    height: Number.isFinite(height) && height > 0 ? height : 1024,
  };
}

function outputKind(output: RunOutput, artifact: OutputArtifact): GalleryItem["type"] {
  const filename = String(artifact.filename || "").toLowerCase();
  const type = String(output.type || artifact.type || "").toLowerCase();
  if (type === "video" || /\.(mp4|webm|mov|mkv)$/.test(filename)) return "video";
  if (type === "image" || /\.(png|jpe?g|webp|gif|bmp)$/.test(filename)) return "image";
  return "json";
}

function copyText(text: string) {
  return navigator.clipboard?.writeText(text).then(
    () => true,
    () => {
      const textarea = document.createElement("textarea");
      textarea.value = text;
      textarea.style.position = "fixed";
      textarea.style.left = "-9999px";
      document.body.appendChild(textarea);
      textarea.focus();
      textarea.select();
      const copied = document.execCommand("copy");
      textarea.remove();
      return copied;
    },
  );
}

function valueForSubmit(input: ContractInput, value: unknown) {
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

function App() {
  const [contractsData, setContractsData] = useState<ContractsResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [status, setStatus] = useState("Ready");
  const [issues, setIssues] = useState<RunIssue[]>([]);
  const [gallery, setGallery] = useState<GalleryItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [rawResult, setRawResult] = useState<RunResponse | null>(null);
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    const hasPending = gallery.some((item) => item.status === "pending");
    if (!hasPending) return;
    const interval = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(interval);
  }, [gallery]);

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

  async function refresh() {
    setStatus("Loading contracts");
    try {
      const [nextContracts, nextHealth] = await Promise.all([
        apiJson<ContractsResponse>("/contracts"),
        apiJson<HealthResponse>("/health"),
      ]);
      setContractsData(nextContracts);
      setHealth(nextHealth);
      setStatus("Ready");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not load contracts");
    }
  }

  async function runSelected() {
    if (!selected || busy) return;
    setBusy(true);
    setIssues([]);
    setRawResult(null);
    setStatus("Submitting");
    const submitInputs: Record<string, unknown> = {};
    for (const input of selected.inputs) {
      submitInputs[input.name] = valueForSubmit(input, inputs[input.name]);
    }
    const dimensions = imageDimensions(submitInputs);
    const pendingId = `pending-${selected.workflow}-${selected.contract}-${Date.now()}`;
    setGallery((current) => [
      {
        id: pendingId,
        contract: contractTitle(selected),
        type: "image",
        status: "pending",
        width: dimensions.width,
        height: dimensions.height,
        inputs: submitInputs,
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
          body: JSON.stringify({ inputs: submitInputs, wait: true }),
        },
      );
      setRawResult(result);
      setIssues(result.issues || []);
      const nextItems: GalleryItem[] = [];
      for (const output of result.outputs || []) {
        for (const artifact of output.artifacts || []) {
          const type = outputKind(output, artifact);
          nextItems.push({
            id: `${result.prompt_id || Date.now()}-${output.name}-${artifact.filename || nextItems.length}`,
            contract: contractTitle(selected),
            promptId: result.prompt_id,
            output,
            artifact,
            filename: artifact.filename,
            outputName: output.name,
            type,
            url: artifact.url,
            status: "done",
            width: type === "image" || type === "video" ? dimensions.width : 1,
            height: type === "image" || type === "video" ? dimensions.height : 1,
            inputs: submitInputs,
            createdAt: new Date().toISOString(),
          });
        }
      }
      if (nextItems.length) {
        setGallery((current) => [...nextItems, ...current.filter((item) => item.id !== pendingId)]);
      } else {
        setGallery((current) => current.filter((item) => item.id !== pendingId));
      }
      setStatus(result.status === "completed" ? "Completed" : result.status);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Generation failed";
      setStatus(message);
      setGallery((current) =>
        current.map((item) => (item.id === pendingId ? { ...item, status: "error", error: message } : item)),
      );
    } finally {
      setBusy(false);
    }
  }

  async function copyGalleryItem(item: GalleryItem) {
    if (!item.url) {
      await copyText(JSON.stringify(item.artifact?.raw || item.artifact || item.inputs || {}, null, 2));
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
  }

  function deleteGalleryItem(item: GalleryItem) {
    setGallery((current) => current.filter((candidate) => candidate.id !== item.id));
    setActiveId((current) => (current === item.id ? null : current));
  }

  const visibleGallery = gallery.filter((item) => item.status !== "error" || item.error);
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

        {visibleGallery.length ? (
          <section className="gallery" aria-label="Generated outputs">
            <MasonryPhotoAlbum<GalleryPhoto>
              photos={visibleGallery.map(galleryPhoto)}
              spacing={7}
              padding={0}
              columns={(containerWidth) =>
                containerWidth < 620 ? 2 : containerWidth < 980 ? 3 : containerWidth < 1400 ? 4 : containerWidth < 1900 ? 5 : 6
              }
              render={{
                photo: (_, { photo, width, height }) => (
                  <GalleryTile
                    key={photo.item.id}
                    item={photo.item}
                    width={width}
                    height={height}
                    now={now}
                    onOpen={setActiveId}
                    onCopy={copyGalleryItem}
                    onDelete={deleteGalleryItem}
                  />
                ),
              }}
            />
          </section>
        ) : (
          <div className="empty-stage">
            <p>Run a contract to collect outputs here.</p>
          </div>
        )}
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
            {selected ? (
              <div className="contract-summary">
                <strong>{selected.workflow}</strong>
                <span>
                  {selected.inputs.length} inputs / {selected.outputs.length} outputs
                </span>
              </div>
            ) : null}
          </section>
        ) : null}

        {selected ? (
          <section className="runner-card">
            <div className="runner-head">
              <div>
                <p className="eyebrow">Selected</p>
                <h2>{contractTitle(selected)}</h2>
              </div>
              <span className="status-chip">{status}</span>
            </div>

            {selected.description ? <p className="description">{selected.description}</p> : null}

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

function ContractInputControl({
  input,
  value,
  onChange,
}: {
  input: ContractInput;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const id = `input-${input.name}`;
  const label = labelFor(input);
  const required = input.required ? "required" : "optional";

  if (input.type === "boolean") {
    return (
      <label className="toggle-field" htmlFor={id}>
        <span>
          <strong>{label}</strong>
          <em>{required}</em>
        </span>
        <input
          id={id}
          type="checkbox"
          checked={Boolean(value)}
          onChange={(event) => onChange(event.target.checked)}
        />
      </label>
    );
  }

  if (input.type === "enum" && input.enum_values?.length) {
    return (
      <Field label={label} meta={required}>
        <StudioSelect value={String(value ?? "")} onChange={onChange} options={input.enum_values} />
      </Field>
    );
  }

  if (input.type === "integer" || input.type === "number") {
    const numeric = Number(value ?? input.default ?? input.min ?? 0);
    const min = Number.isFinite(input.min) ? Number(input.min) : 0;
    const max = Number.isFinite(input.max) ? Number(input.max) : Number.POSITIVE_INFINITY;
    const integerLike =
      input.type === "integer" ||
      (Number.isInteger(numeric) &&
        (input.min === undefined || Number.isInteger(input.min)) &&
        (input.max === undefined || Number.isInteger(input.max)));
    return (
      <NumberPicker
        label={label}
        meta={required}
        value={Number.isFinite(numeric) ? numeric : min}
        min={min}
        max={max}
        step={integerLike ? 1 : 0.01}
        precision={integerLike ? 0 : undefined}
        fill
        onChange={onChange}
      />
    );
  }

  const longText = input.type === "string" && /prompt|text|description/i.test(input.name);
  return (
    <Field
      label={label}
      meta={
        <>
          {required} · {compactType(input.type)}
        </>
      }
    >
      {longText ? (
        <textarea id={id} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} />
      ) : (
        <input id={id} value={String(value ?? "")} onChange={(event) => onChange(event.target.value)} />
      )}
    </Field>
  );
}

function formatElapsed(ms: number) {
  const seconds = Math.max(0, Math.floor(ms / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${seconds % 60}s`;
}

function GalleryTile({
  item,
  width,
  height,
  now,
  onOpen,
  onCopy,
  onDelete,
}: {
  item: GalleryItem;
  width: number;
  height: number;
  now: number;
  onOpen: (id: string) => void;
  onCopy: (item: GalleryItem) => void;
  onDelete: (item: GalleryItem) => void;
}) {
  return (
    <button
      className={cn("tile", item.status)}
      style={{ width, height, "--tile-ratio": `${item.width || 1} / ${item.height || 1}` } as React.CSSProperties}
      type="button"
      onClick={() => item.status !== "pending" && onOpen(item.id)}
    >
      {item.status === "pending" ? (
        <div className="generating">
          <div className="noise-layer" />
          <div className="generate-overlay">
            <span className="generate-step-label is-queued">Rendering</span>
            <span className="generate-elapsed">{formatElapsed(now - Date.parse(item.createdAt))}</span>
          </div>
          <div className="generate-bar is-indeterminate">
            <div className="generate-bar-fill" />
          </div>
        </div>
      ) : item.status === "done" ? (
        <Media item={item} muted />
      ) : (
        <div className="generating stopped">
          <span>{item.error || "Generation failed"}</span>
        </div>
      )}
      <span className="tile-caption">
        <strong>{titleFromOutput(item.outputName || item.filename || item.contract)}</strong>
        <em>{item.filename || item.contract}</em>
      </span>
      {item.status !== "pending" ? (
        <span className="tile-hover-actions">
          {item.url ? (
            <Tip content="Download" side="left" className="tile-action-tooltip">
              <a className="tile-icon" aria-label="Download" href={item.url} download onClick={(event) => event.stopPropagation()}>
                <Download size={13} />
              </a>
            </Tip>
          ) : null}
          <Tip content="Copy" side="left" className="tile-action-tooltip">
            <span
              className="tile-icon"
              role="button"
              aria-label="Copy"
              onClick={(event) => {
                event.stopPropagation();
                void onCopy(item);
              }}
            >
              <Copy size={14} />
            </span>
          </Tip>
          <Tip content="Delete from gallery" side="left" className="tile-action-tooltip">
            <span
              className="tile-delete"
              role="button"
              aria-label="Delete from gallery"
              onClick={(event) => {
                event.stopPropagation();
                onDelete(item);
              }}
            >
              <Trash2 size={14} />
            </span>
          </Tip>
        </span>
      ) : null}
    </button>
  );
}

function OutputViewer({
  item,
  hasNeighbors,
  onClose,
  onMove,
  onCopy,
  onDelete,
}: {
  item: GalleryItem;
  hasNeighbors: boolean;
  onClose: () => void;
  onMove: (delta: number) => void;
  onCopy: (item: GalleryItem) => void;
  onDelete: (item: GalleryItem) => void;
}) {
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);
  const dragRef = useRef<{ id: number; x: number; y: number; panX: number; panY: number; moved: boolean } | null>(null);
  const dragEndRef = useRef(0);

  useEffect(() => {
    setZoom(1);
    setPan({ x: 0, y: 0 });
    dragRef.current = null;
    dragEndRef.current = 0;
  }, [item.id]);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "ArrowLeft") onMove(-1);
      if (event.key === "ArrowRight") onMove(1);
      if (event.key === "Delete" || event.key === "Backspace") onDelete(item);
      if (event.key === "+" || event.key === "=") zoomViewer(zoom + 0.25);
      if (event.key === "-") zoomViewer(zoom - 0.25);
      if (event.key === "0") resetViewer();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [item, onClose, onDelete, onMove, zoom]);

  function resetViewer() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }

  function zoomViewer(nextZoom: number, anchor?: { x: number; y: number; element: HTMLElement }) {
    const clamped = Math.max(0.5, Math.min(6, Number(nextZoom.toFixed(2))));
    if (anchor && clamped > 1) {
      const rect = anchor.element.getBoundingClientRect();
      const anchorX = anchor.x - rect.left - rect.width / 2;
      const anchorY = anchor.y - rect.top - rect.height / 2;
      const scale = clamped / Math.max(zoom, 0.01);
      setPan({
        x: anchorX - (anchorX - pan.x) * scale,
        y: anchorY - (anchorY - pan.y) * scale,
      });
    } else if (clamped <= 1) {
      setPan({ x: 0, y: 0 });
    }
    setZoom(clamped);
  }

  function wheelViewer(event: React.WheelEvent<HTMLDivElement>) {
    event.preventDefault();
    event.stopPropagation();
    const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
    zoomViewer(zoom * factor, { x: event.clientX, y: event.clientY, element: event.currentTarget });
  }

  function clickViewer(event: React.MouseEvent<HTMLDivElement>) {
    event.stopPropagation();
    if (Date.now() - dragEndRef.current < 220) return;
    if (dragRef.current?.moved) return;
    const media = event.currentTarget.querySelector("img, video") as HTMLElement | null;
    if (!media) return;
    const rect = media.getBoundingClientRect();
    const inside =
      event.clientX >= rect.left &&
      event.clientX <= rect.right &&
      event.clientY >= rect.top &&
      event.clientY <= rect.bottom;
    if (!inside) onClose();
  }

  function startViewerDrag(event: React.PointerEvent<HTMLDivElement>) {
    if (zoom <= 1) return;
    event.preventDefault();
    event.stopPropagation();
    event.currentTarget.setPointerCapture(event.pointerId);
    dragRef.current = {
      id: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      panX: pan.x,
      panY: pan.y,
      moved: false,
    };
    setIsDragging(true);
  }

  function dragViewer(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (!drag || drag.id !== event.pointerId) return;
    event.preventDefault();
    event.stopPropagation();
    const dx = event.clientX - drag.x;
    const dy = event.clientY - drag.y;
    if (Math.abs(dx) > 3 || Math.abs(dy) > 3) drag.moved = true;
    if (zoom > 1) setPan({ x: drag.panX + dx, y: drag.panY + dy });
  }

  function stopViewerDrag(event: React.PointerEvent<HTMLDivElement>) {
    const drag = dragRef.current;
    if (drag?.id === event.pointerId) {
      event.preventDefault();
      event.stopPropagation();
      if (drag.moved) dragEndRef.current = Date.now();
      setIsDragging(false);
      window.setTimeout(() => {
        dragRef.current = null;
      }, 0);
    }
  }

  return (
    <div className="scrim" onWheel={(event) => event.preventDefault()}>
      <div className="viewer-shell">
        <div className="viewer-stage">
          <div
            className={cn("viewer-canvas", zoom > 1 && "is-zoomed", isDragging && "is-dragging")}
            style={{ "--zoom": zoom, "--pan-x": `${pan.x}px`, "--pan-y": `${pan.y}px` } as React.CSSProperties}
            onWheel={wheelViewer}
            onPointerDown={startViewerDrag}
            onPointerMove={dragViewer}
            onPointerUp={stopViewerDrag}
            onPointerCancel={stopViewerDrag}
            onDragStart={(event) => event.preventDefault()}
            onClick={clickViewer}
            onDoubleClick={(event) => {
              event.stopPropagation();
              zoomViewer(zoom > 1 ? 1 : 2.5, { x: event.clientX, y: event.clientY, element: event.currentTarget });
            }}
          >
            <Media item={item} />
          </div>
          {hasNeighbors ? (
            <>
              <Tip content="Previous">
                <button className="viewer-arrow prev" type="button" aria-label="Previous output" onClick={() => onMove(-1)}>
                  <ChevronLeft size={20} />
                </button>
              </Tip>
              <Tip content="Next">
                <button className="viewer-arrow next" type="button" aria-label="Next output" onClick={() => onMove(1)}>
                  <ChevronRight size={20} />
                </button>
              </Tip>
            </>
          ) : null}
          <div className="viewer-dock" onClick={(event) => event.stopPropagation()}>
            <Tip content="Zoom out">
              <button className="icon-button" type="button" aria-label="Zoom out" onClick={() => zoomViewer(zoom - 0.25)} disabled={zoom <= 0.5}>
                <ZoomOut size={15} />
              </button>
            </Tip>
            <Tip content="Reset zoom">
              <button className="text-button viewer-zoom" type="button" aria-label="Reset zoom" onClick={resetViewer}>
                {zoom !== 1 ? <RotateCcw size={13} /> : null}
                {Math.round(zoom * 100)}%
              </button>
            </Tip>
            <Tip content="Zoom in">
              <button className="icon-button" type="button" aria-label="Zoom in" onClick={() => zoomViewer(zoom + 0.25)} disabled={zoom >= 6}>
                <ZoomIn size={15} />
              </button>
            </Tip>
            <span className="viewer-divider" />
            <Tip content={item.type === "image" ? "Copy image" : "Copy output link"}>
              <button className="icon-button" type="button" aria-label="Copy output" onClick={() => void onCopy(item)}>
                <Copy size={15} />
              </button>
            </Tip>
            {item.url ? (
              <Tip content="Download file">
                <a className="icon-button" aria-label="Download file" href={item.url} download>
                  <Download size={15} />
                </a>
              </Tip>
            ) : null}
            <Tip content="Delete">
              <button className="icon-button danger-tone" type="button" aria-label="Delete output" onClick={() => onDelete(item)}>
                <Trash2 size={15} />
              </button>
            </Tip>
            <span className="viewer-divider" />
            <Tip content="Close">
              <button className="icon-button" type="button" aria-label="Close" onClick={onClose}>
                <X size={16} />
              </button>
            </Tip>
          </div>
        </div>
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ShapeProvider defaultShape="rounded">
      <App />
    </ShapeProvider>
  </React.StrictMode>,
);
