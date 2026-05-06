import type { CSSProperties } from "react";
import { Copy, Download, Trash2 } from "lucide-react";
import { Media, Tip } from "@/app/components";
import { formatElapsed, titleFromOutput } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { GalleryItem } from "@/types";

export function GalleryTile({
  item,
  width,
  height,
  fill,
  now,
  onOpen,
  onCopy,
  onDelete,
}: {
  item: GalleryItem;
  width?: number;
  height?: number;
  fill?: boolean;
  now: number;
  onOpen: (id: string) => void;
  onCopy: (item: GalleryItem) => void;
  onDelete: (item: GalleryItem) => void;
}) {
  const ratio = `${item.width || 1} / ${item.height || 1}`;
  return (
    <button
      className={cn("tile", item.status)}
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
