"use client";

import { forwardRef, useRef, useEffect, useState, useCallback, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { motion, AnimatePresence } from "framer-motion";
import { cn } from "@/lib/utils";
import { springs } from "@/lib/springs";
import { useProximityHover } from "@/hooks/use-proximity-hover";
import { useShape } from "@/lib/shape-context";
import { SelectContentContext, useSelectContext } from "./select";

export interface SelectContentProps {
  className?: string;
  children: ReactNode;
}

export const SelectContent = forwardRef<HTMLDivElement, SelectContentProps>(
  ({ className, children }, ref) => {
    const { open, setOpen, value, triggerRef } = useSelectContext();
    const shape = useShape();
    const containerRef = useRef<HTMLDivElement>(null);
    const [triggerRect, setTriggerRect] = useState<DOMRect | null>(null);

    const {
      activeIndex,
      setActiveIndex,
      itemRects,
      sessionRef,
      handlers,
      registerItem,
      measureItems,
    } = useProximityHover(containerRef);

    const [focusedIndex, setFocusedIndex] = useState<number | null>(null);
    const [checkedIndex, setCheckedIndex] = useState<number | undefined>(
      undefined
    );

    // Capture trigger rect synchronously when opening
    useEffect(() => {
      if (open && triggerRef.current) {
        setTriggerRect(triggerRef.current.getBoundingClientRect());
      }
    }, [open, triggerRef]);

    // Measure items + detect checked AFTER the portal has mounted
    // triggerRect being set means the portal will render on the next commit
    useEffect(() => {
      if (!open || !triggerRect) return;
      // Double rAF: first waits for React commit, second for layout
      let outer: number;
      let inner: number;
      outer = requestAnimationFrame(() => {
        inner = requestAnimationFrame(() => {
          measureItems();
          const container = containerRef.current;
          if (container) {
            const items = Array.from(
              container.querySelectorAll("[data-proximity-index]")
            ) as HTMLElement[];
            const idx = items.findIndex(
              (el) => el.getAttribute("data-value") === value
            );
            if (idx !== -1) setCheckedIndex(idx);
            else setCheckedIndex(undefined);

            // Focus the container so keyboard events work;
            // don't focus an item directly to avoid showing a focus ring
            containerRef.current?.focus({ preventScroll: true });
          }
        });
      });
      return () => {
        cancelAnimationFrame(outer);
        cancelAnimationFrame(inner);
      };
    }, [open, triggerRect, measureItems, value]);

    // Close on escape
    useEffect(() => {
      if (!open) return;
      const onKey = (e: KeyboardEvent) => {
        if (e.key === "Escape") {
          setOpen(false);
          triggerRef.current?.focus();
        }
      };
      document.addEventListener("keydown", onKey);
      return () => document.removeEventListener("keydown", onKey);
    }, [open, setOpen, triggerRef]);

    // Close on click outside
    useEffect(() => {
      if (!open) return;
      const onPointer = (e: MouseEvent) => {
        if (
          !containerRef.current?.contains(e.target as Node) &&
          !triggerRef.current?.contains(e.target as Node)
        ) {
          setOpen(false);
        }
      };
      document.addEventListener("mousedown", onPointer);
      return () => document.removeEventListener("mousedown", onPointer);
    }, [open, setOpen, triggerRef]);

    // Close on scroll (instead of locking body scroll, which causes layout shift)
    useEffect(() => {
      if (!open) return;
      const onScroll = () => setOpen(false);
      window.addEventListener("scroll", onScroll, { passive: true });
      return () => window.removeEventListener("scroll", onScroll);
    }, [open, setOpen]);

    // Keyboard nav inside content
    const handleKeyDown = useCallback(
      (e: React.KeyboardEvent) => {
        const items = Array.from(
          containerRef.current?.querySelectorAll(
            '[role="option"]:not([data-disabled])'
          ) ?? []
        ) as HTMLElement[];
        const currentIdx = items.indexOf(e.target as HTMLElement);

        if (
          ["ArrowDown", "ArrowUp", "ArrowRight", "ArrowLeft"].includes(e.key)
        ) {
          e.preventDefault();
          if (currentIdx === -1) {
            // No item focused yet — focus checked or first item
            const checked =
              value !== ""
                ? items.find((item) => item.getAttribute("data-value") === value)
                : null;
            (checked ?? items[0])?.focus();
          } else {
            const next = ["ArrowDown", "ArrowRight"].includes(e.key)
              ? (currentIdx + 1) % items.length
              : (currentIdx - 1 + items.length) % items.length;
            items[next]?.focus();
          }
        } else if (e.key === "Home") {
          e.preventDefault();
          items[0]?.focus();
        } else if (e.key === "End") {
          e.preventDefault();
          items[items.length - 1]?.focus();
        }
      },
      [value]
    );

    // Render hidden when closed so items can register labels
    if (!open) {
      return (
        <div hidden aria-hidden="true">
          {children}
        </div>
      );
    }

    if (!triggerRect) return null;

    const activeRect = activeIndex !== null ? itemRects[activeIndex] : null;
    const checkedRect =
      checkedIndex != null ? itemRects[checkedIndex] : null;
    const focusRect = focusedIndex !== null ? itemRects[focusedIndex] : null;
    const isHoveringOther =
      activeIndex !== null && activeIndex !== checkedIndex;

    return createPortal(
      <SelectContentContext.Provider
        value={{ registerItem, activeIndex, checkedIndex }}
      >
        <div
          data-open-surface
          style={{
            position: "fixed",
            top: triggerRect.bottom + 6,
            left: triggerRect.left,
            minWidth: triggerRect.width,
            zIndex: 50,
          }}
        >
          <motion.div
            initial={{ opacity: 0, y: -4, scaleY: 0.96 }}
            animate={{ opacity: 1, y: 0, scaleY: 1 }}
            transition={springs.fast}
            style={{ transformOrigin: "top center" }}
          >
          <div
            ref={(node) => {
              (
                containerRef as React.MutableRefObject<HTMLDivElement | null>
              ).current = node;
              if (typeof ref === "function") ref(node);
              else if (ref)
                (
                  ref as React.MutableRefObject<HTMLDivElement | null>
                ).current = node;
            }}
            role="listbox"
            tabIndex={-1}
            onMouseEnter={() => {
              handlers.onMouseEnter();
              setFocusedIndex(null);
            }}
            onMouseMove={handlers.onMouseMove}
            onMouseLeave={handlers.onMouseLeave}
            onFocus={(e) => {
              const indexAttr = (e.target as HTMLElement)
                .closest("[data-proximity-index]")
                ?.getAttribute("data-proximity-index");
              if (indexAttr != null) {
                const idx = Number(indexAttr);
                setActiveIndex(idx);
                setFocusedIndex(
                  (e.target as HTMLElement).matches(":focus-visible")
                    ? idx
                    : null
                );
              }
            }}
            onBlur={(e) => {
              if (containerRef.current?.contains(e.relatedTarget as Node))
                return;
              setFocusedIndex(null);
              setActiveIndex(null);
            }}
            onKeyDown={handleKeyDown}
            className={cn(
              `relative flex flex-col gap-0.5 max-h-[300px] overflow-y-auto ${shape.container} bg-card shadow-[0_4px_12px_rgba(0,0,0,0.02)] dark:shadow-[0_8px_32px_rgba(0,0,0,0.5)] border border-border/60 p-1 select-none outline-none`,
              className
            )}
          >
            {/* Selected background */}
            <AnimatePresence>
              {checkedRect && (
                <motion.div
                  className={`absolute ${shape.bg} bg-selected/50 dark:bg-accent/40 pointer-events-none`}
                  initial={false}
                  animate={{
                    top: checkedRect.top,
                    left: checkedRect.left,
                    width: checkedRect.width,
                    height: checkedRect.height,
                    opacity: isHoveringOther ? 0.8 : 1,
                  }}
                  exit={{ opacity: 0, transition: { duration: 0.12 } }}
                  transition={{
                    ...springs.moderate,
                    opacity: { duration: 0.08 },
                  }}
                />
              )}
            </AnimatePresence>

            {/* Hover background */}
            <AnimatePresence>
              {activeRect && (
                <motion.div
                  key={sessionRef.current}
                  className={`absolute ${shape.bg} bg-accent/40 dark:bg-accent/25 pointer-events-none`}
                  initial={{
                    opacity: 0,
                    top: checkedRect?.top ?? activeRect.top,
                    left: checkedRect?.left ?? activeRect.left,
                    width: checkedRect?.width ?? activeRect.width,
                    height: checkedRect?.height ?? activeRect.height,
                  }}
                  animate={{
                    opacity: 1,
                    top: activeRect.top,
                    left: activeRect.left,
                    width: activeRect.width,
                    height: activeRect.height,
                  }}
                  exit={{ opacity: 0, transition: { duration: 0.06 } }}
                  transition={{
                    ...springs.fast,
                    opacity: { duration: 0.08 },
                  }}
                />
              )}
            </AnimatePresence>

            {/* Focus ring */}
            <AnimatePresence>
              {focusRect && (
                <motion.div
                  className={`absolute ${shape.focusRing} pointer-events-none z-20 border border-[#6B97FF]`}
                  initial={false}
                  animate={{
                    left: focusRect.left - 2,
                    top: focusRect.top - 2,
                    width: focusRect.width + 4,
                    height: focusRect.height + 4,
                  }}
                  exit={{ opacity: 0, transition: { duration: 0.06 } }}
                  transition={{
                    ...springs.fast,
                    opacity: { duration: 0.08 },
                  }}
                />
              )}
            </AnimatePresence>

            {children}
          </div>
          </motion.div>
        </div>
      </SelectContentContext.Provider>,
      document.body
    );
  }
);

SelectContent.displayName = "SelectContent";

// ---------------------------------------------------------------------------
