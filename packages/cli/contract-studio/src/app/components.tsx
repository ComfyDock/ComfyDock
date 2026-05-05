import React, { useEffect, useRef, useState } from "react";
import { Minus, Plus } from "lucide-react";
import {
  Select as FluidSelect,
  SelectContent as FluidSelectContent,
  SelectItem as FluidSelectItem,
  SelectTrigger as FluidSelectTrigger,
} from "@/components/ui/select";
import { Tooltip as FluidTooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export function Field({
  label,
  meta,
  children,
}: {
  label: string;
  meta?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <label className="field">
      <span>
        {label}
        {meta ? <em className="field-meta">{meta}</em> : null}
      </span>
      {children}
    </label>
  );
}

export function Skeleton({ className = "" }: { className?: string }) {
  return <span className={cn("skeleton", className)} aria-hidden="true" />;
}

export function Media({
  item,
  muted = false,
}: {
  item: { url?: string; type?: string; filename?: string; outputName?: string; error?: string; artifact?: unknown };
  muted?: boolean;
}) {
  const [loaded, setLoaded] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    setLoaded(false);
    setFailed(false);
  }, [item.url]);

  if (!item.url || failed) {
    return (
      <div className="media-fallback">
        <span>{item.error || item.filename || item.outputName || "Output unavailable"}</span>
      </div>
    );
  }

  if (item.type === "video") {
    return (
      <video
        className={cn(!loaded && "media-loading")}
        src={item.url}
        controls={!muted}
        muted={muted}
        loop
        autoPlay={muted}
        preload="metadata"
        draggable={false}
        onLoadedData={() => setLoaded(true)}
        onError={() => setFailed(true)}
      />
    );
  }

  if (item.type === "image") {
    return (
      <img
        className={cn(!loaded && "media-loading")}
        src={item.url}
        alt={item.filename || item.outputName || "Generated output"}
        loading="lazy"
        decoding="async"
        draggable={false}
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
        onDragStart={(event) => event.preventDefault()}
      />
    );
  }

  return (
    <div className="media-fallback">
      <span>{item.filename || item.outputName || "Structured output"}</span>
    </div>
  );
}

export function StudioSelect({
  value,
  onChange,
  options,
  placeholder = "Select",
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  options: Array<string | { label: string; value: string }>;
  placeholder?: string;
  disabled?: boolean;
}) {
  const normalized = options.map((option) =>
    typeof option === "string" ? { label: option, value: option } : option,
  );
  return (
    <FluidSelect value={value} onValueChange={onChange} disabled={disabled}>
      <FluidSelectTrigger className="fluid-select-trigger" placeholder={placeholder} />
      <FluidSelectContent className="fluid-select-content">
        {normalized.map((item, index) => (
          <FluidSelectItem key={item.value} index={index} value={item.value}>
            {item.label}
          </FluidSelectItem>
        ))}
      </FluidSelectContent>
    </FluidSelect>
  );
}

export function Tip({
  content,
  side = "bottom",
  className,
  children,
}: {
  content: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  className?: string;
  children: React.ReactElement;
}) {
  return (
    <FluidTooltip content={content} side={side} sideOffset={8} delayDuration={120} className={className}>
      {children}
    </FluidTooltip>
  );
}

export function NumberPicker({
  label,
  meta,
  value,
  onChange,
  min = 0,
  max = Number.POSITIVE_INFINITY,
  step = 1,
  precision,
  size = "md",
  fill = false,
}: {
  label: string;
  meta?: React.ReactNode;
  value: number;
  onChange: (next: number) => void;
  min?: number;
  max?: number;
  step?: number;
  precision?: number;
  size?: "sm" | "md";
  fill?: boolean;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(String(value));
  const inputRef = useRef<HTMLInputElement | null>(null);
  const valueRef = useRef(value);
  const holdRef = useRef<{ timer: number | null; interval: number | null }>({
    timer: null,
    interval: null,
  });

  const decimals =
    precision ?? (Number.isInteger(step) ? 0 : Math.min(4, (String(step).split(".")[1] || "").length));
  const formatValue = (n: number) => (decimals > 0 ? n.toFixed(decimals) : String(Math.round(n)));

  useEffect(() => {
    valueRef.current = value;
  }, [value]);
  useEffect(() => {
    if (!editing) setDraft(formatValue(value));
  }, [value, editing, decimals]);

  const clamp = (n: number) => {
    const bounded = Math.max(min, Math.min(max, n));
    if (decimals === 0) return Math.round(bounded);
    const factor = Math.pow(10, decimals);
    return Math.round(bounded * factor) / factor;
  };

  const stepBy = (direction: number) => {
    const next = clamp(valueRef.current + direction * step);
    if (next !== valueRef.current) onChange(next);
  };

  const clearHold = () => {
    if (holdRef.current.timer) window.clearTimeout(holdRef.current.timer);
    if (holdRef.current.interval) window.clearInterval(holdRef.current.interval);
    holdRef.current = { timer: null, interval: null };
  };

  const startHold = (direction: number) => {
    stepBy(direction);
    holdRef.current.timer = window.setTimeout(() => {
      holdRef.current.interval = window.setInterval(() => stepBy(direction), 55);
    }, 320);
  };

  useEffect(() => () => clearHold(), []);

  const beginEdit = () => {
    setDraft(formatValue(value));
    setEditing(true);
    requestAnimationFrame(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    });
  };

  const commitEdit = () => {
    const parsed = Number(draft);
    if (Number.isFinite(parsed)) onChange(clamp(parsed));
    setEditing(false);
  };

  const labelLower = label.toLowerCase();
  return (
    <div
      className={cn("number-picker", size === "sm" && "is-sm", fill && "is-fill")}
      onWheel={(event) => {
        event.preventDefault();
        stepBy(event.deltaY < 0 ? 1 : -1);
      }}
    >
      <span className="number-picker-label">
        {label}
        {meta ? <em>{meta}</em> : null}
      </span>
      <Tip content={`Decrease ${labelLower}`}>
        <button
          type="button"
          className="number-picker-btn"
          aria-label={`Decrease ${labelLower}`}
          disabled={value <= min}
          onPointerDown={(event) => {
            event.preventDefault();
            startHold(-1);
          }}
          onPointerUp={clearHold}
          onPointerLeave={clearHold}
          onPointerCancel={clearHold}
        >
          <Minus size={12} />
        </button>
      </Tip>
      {editing ? (
        <input
          ref={inputRef}
          className="number-picker-input"
          type="number"
          min={min}
          max={Number.isFinite(max) ? max : undefined}
          step={step}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={commitEdit}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commitEdit();
            } else if (event.key === "Escape") {
              setDraft(formatValue(value));
              setEditing(false);
            } else if (event.key === "ArrowUp") {
              event.preventDefault();
              stepBy(1);
            } else if (event.key === "ArrowDown") {
              event.preventDefault();
              stepBy(-1);
            }
          }}
        />
      ) : (
        <button
          type="button"
          className="number-picker-value"
          onClick={beginEdit}
          aria-label={`${label}: ${formatValue(value)}, click to edit`}
        >
          {formatValue(value)}
        </button>
      )}
      <Tip content={`Increase ${labelLower}`}>
        <button
          type="button"
          className="number-picker-btn"
          aria-label={`Increase ${labelLower}`}
          disabled={value >= max}
          onPointerDown={(event) => {
            event.preventDefault();
            startHold(1);
          }}
          onPointerUp={clearHold}
          onPointerLeave={clearHold}
          onPointerCancel={clearHold}
        >
          <Plus size={12} />
        </button>
      </Tip>
    </div>
  );
}
