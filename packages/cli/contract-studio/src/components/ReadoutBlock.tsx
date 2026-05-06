import { Copy } from "lucide-react";
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
  return (
    <div className="prompt-readout">
      {hideTitle ? null : <span>{title}</span>}
      <div className="readout-box">
        <pre>{value}</pre>
        <Tip content={`Copy ${title.toLowerCase()}`}>
          <button className="readout-copy" aria-label={`Copy ${title}`} onClick={() => void copyText(value)}>
            <Copy size={13} />
          </button>
        </Tip>
      </div>
    </div>
  );
}
