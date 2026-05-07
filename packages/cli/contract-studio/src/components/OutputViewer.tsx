import React, { useEffect, useRef, useState, type CSSProperties } from "react";
import { ChevronDown, ChevronLeft, ChevronRight, Copy, Download, RotateCcw, Trash2, X, ZoomIn, ZoomOut } from "lucide-react";
import { Media, Tip } from "@/app/components";
import { ReadoutBlock } from "@/components/ReadoutBlock";
import { formatGeneratedAt, jsonBlock, titleFromOutput } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { GalleryItem } from "@/types";

export function OutputViewer({
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
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const isZoomable = item.type === "image";

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
      if (!isZoomable) return;
      if (event.key === "+" || event.key === "=") zoomViewer(zoom + 0.25);
      if (event.key === "-") zoomViewer(zoom - 0.25);
      if (event.key === "0") resetViewer();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [isZoomable, item, onClose, onDelete, onMove, zoom]);

  useEffect(() => {
    if (!isZoomable) return;
    const canvas = canvasRef.current;
    if (!canvas) return;

    const onWheel = (event: WheelEvent) => {
      event.preventDefault();
      event.stopPropagation();
      const factor = event.deltaY < 0 ? 1.12 : 1 / 1.12;
      zoomViewer(zoom * factor, { x: event.clientX, y: event.clientY, element: canvas });
    };

    canvas.addEventListener("wheel", onWheel, { passive: false });
    return () => canvas.removeEventListener("wheel", onWheel);
  }, [isZoomable, pan.x, pan.y, zoom]);

  function resetViewer() {
    setZoom(1);
    setPan({ x: 0, y: 0 });
  }

  function zoomViewer(nextZoom: number, anchor?: { x: number; y: number; element: HTMLElement }) {
    if (!isZoomable) return;
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

  function clickViewer(event: React.MouseEvent<HTMLDivElement>) {
    event.stopPropagation();
    if (Date.now() - dragEndRef.current < 220) return;
    if (dragRef.current?.moved) return;
    const media = event.currentTarget.querySelector("img, video, .media-fallback") as HTMLElement | null;
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
    if (!isZoomable || zoom <= 1) return;
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
    <div className="scrim">
      <div className="viewer-shell">
        <div className="viewer-stage">
          <div
            ref={canvasRef}
            className={cn("viewer-canvas", !isZoomable && "is-interactive-media", zoom > 1 && "is-zoomed", isDragging && "is-dragging")}
            style={{ "--zoom": zoom, "--pan-x": `${pan.x}px`, "--pan-y": `${pan.y}px` } as CSSProperties}
            onPointerDown={startViewerDrag}
            onPointerMove={dragViewer}
            onPointerUp={stopViewerDrag}
            onPointerCancel={stopViewerDrag}
            onDragStart={(event) => event.preventDefault()}
            onClick={clickViewer}
            onDoubleClick={(event) => {
              if (!isZoomable) return;
              event.stopPropagation();
              zoomViewer(zoom > 1 ? 1 : 2.5, { x: event.clientX, y: event.clientY, element: event.currentTarget });
            }}
          >
            <Media item={item} />
          </div>
          <aside className="viewer-side" onClick={(event) => event.stopPropagation()} onWheel={(event) => event.stopPropagation()}>
            <div className="viewer-side-head">
              <div>
                <p className="eyebrow">Generation Details</p>
                <h3>{item.filename || titleFromOutput(item.outputName)}</h3>
              </div>
            </div>
            <div className="viewer-side-body">
              <div className="detail-grid">
                <span>Contract</span>
                <strong>{item.contract}</strong>
                <span>Workflow</span>
                <strong>{item.contractWorkflow || "Unknown"}</strong>
                <span>Name</span>
                <strong>{item.contractName || "default"}</strong>
                <span>Status</span>
                <strong>{item.status}</strong>
                <span>Generated</span>
                <strong>{formatGeneratedAt(item.createdAt)}</strong>
                <span>Prompt ID</span>
                <strong>{item.promptId || "Not recorded"}</strong>
                <span>Output</span>
                <strong>{item.outputName || "Not recorded"}</strong>
                <span>Type</span>
                <strong>{item.type}</strong>
              </div>

              <ReadoutBlock title="Parameters" value={jsonBlock(item.inputs)} />
              <details className="debug-disclosure">
                <summary>
                  <span>Raw API Output</span>
                  <ChevronDown size={15} />
                </summary>
                <ReadoutBlock
                  title="Raw API Output"
                  value={jsonBlock(item.rawResult || item.error || item.artifact?.raw || item.artifact)}
                  hideTitle
                />
              </details>
            </div>
          </aside>
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
            {isZoomable ? (
              <>
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
              </>
            ) : null}
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
