import { useEffect, useState } from "react";
import { Check, Copy } from "lucide-react";
import { Tip } from "@/app/components";
import { copyText } from "@/lib/clipboard";

export function ReadoutBlock({
  title,
  value,
  hideTitle = false,
}: {
  title: string;
  value: string;
  hideTitle?: boolean;
}) {
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    if (!copied) return;
    const timeout = window.setTimeout(() => setCopied(false), 1100);
    return () => window.clearTimeout(timeout);
  }, [copied]);

  async function copyReadout() {
    const ok = await copyText(value);
    if (ok) setCopied(true);
  }

  return (
    <div className="prompt-readout">
      {hideTitle ? null : <span>{title}</span>}
      <div className="readout-box">
        <pre>{value}</pre>
        <Tip content={copied ? "Copied" : `Copy ${title.toLowerCase()}`}>
          <button
            className={`readout-copy${copied ? " is-copied" : ""}`}
            aria-label={`Copy ${title}`}
            onClick={() => void copyReadout()}
          >
            {copied ? <Check size={14} /> : <Copy size={13} />}
          </button>
        </Tip>
      </div>
    </div>
  );
}
