import { memo, useEffect, useState, type CSSProperties } from "react";
import { Copy, Download, Play, Trash2 } from "lucide-react";
import { Media, Tip } from "@/app/components";
import { downloadGalleryItem } from "@/lib/download";
import { formatElapsed, titleFromOutput } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { GalleryItem } from "@/types";

export const GalleryTile = memo(function GalleryTile({
  item,
  width,
  height,
  fill,
  onOpen,
  onCopy,
  onDelete,
}: {
  item: GalleryItem;
  width?: number;
  height?: number;
  fill?: boolean;
  onOpen: (id: string) => void;
  onCopy: (item: GalleryItem) => void;
  onDelete: (item: GalleryItem) => void;
}) {
  const ratio = `${item.width || 1} / ${item.height || 1}`;
  const [isPreviewing, setIsPreviewing] = useState(false);
  const isVideo = item.status === "done" && item.type === "video";

  useEffect(() => {
    setIsPreviewing(false);
  }, [item.id]);

  return (
    <button
      className={cn("tile", `type-${item.type}`, item.status, isVideo && "has-play-preview", isPreviewing && "is-previewing")}
      style={
        {
          width: fill ? "100%" : width,
          height: fill ? undefined : height,
          aspectRatio: fill ? ratio : undefined,
          "--tile-ratio": ratio,
        } as CSSProperties
      }
      type="button"
      onClick={() => item.status !== "pending" && onOpen(item.id)}
      onMouseEnter={() => isVideo && setIsPreviewing(true)}
      onMouseLeave={() => isVideo && setIsPreviewing(false)}
      onFocus={() => isVideo && setIsPreviewing(true)}
      onBlur={() => isVideo && setIsPreviewing(false)}
    >
      {item.status === "pending" ? (
        <div className="generating">
          <div className="noise-layer" />
          <div className="generate-overlay">
            <span className="generate-step-label is-queued">Rendering</span>
            <PendingElapsed createdAt={item.createdAt} />
          </div>
          <div className="generate-bar is-indeterminate">
            <div className="generate-bar-fill" />
          </div>
        </div>
      ) : item.status === "done" ? (
        <Media
          item={item}
          muted
          autoPlay={isVideo ? isPreviewing : false}
          pauseWhenNotAutoPlaying={item.type === "video"}
          resetOnAutoPlay={false}
        />
      ) : (
        <div className="generating stopped">
          <span>{item.error || (item.status === "cancelled" ? "Cancelled" : "Generation failed")}</span>
        </div>
      )}
      {isVideo ? (
        <span className="tile-play-glyph" aria-hidden="true">
          <Play size={20} fill="currentColor" />
        </span>
      ) : null}
      <span className="tile-caption">
        <strong>{titleFromOutput(item.outputName || item.filename || item.contract)}</strong>
        <em>{item.filename || item.contract}</em>
      </span>
      {item.status !== "pending" ? (
        <span className="tile-hover-actions">
          {item.url ? (
            <Tip content="Download" side="left" className="tile-action-tooltip">
              <span
                className="tile-icon"
                role="button"
                aria-label="Download"
                onClick={(event) => {
                  event.stopPropagation();
                  void downloadGalleryItem(item);
                }}
              >
                <Download size={13} />
              </span>
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
});

function PendingElapsed({ createdAt }: { createdAt: string }) {
  const [elapsed, setElapsed] = useState(() => elapsedSince(createdAt));

  useEffect(() => {
    const update = () => setElapsed(elapsedSince(createdAt));
    update();
    const interval = window.setInterval(update, 1000);
    return () => window.clearInterval(interval);
  }, [createdAt]);

  return <span className="generate-elapsed">{elapsed}</span>;
}

function elapsedSince(createdAt: string) {
  const timestamp = Date.parse(createdAt);
  if (!Number.isFinite(timestamp)) return "0s";
  return formatElapsed(Date.now() - timestamp);
}
