import { useState } from "react";
import { FileAudio, FileUp, FileVideo, ImagePlus } from "lucide-react";
import { Field, NumberPicker, StudioSelect } from "@/app/components";
import { compactType, labelFor } from "@/lib/format";
import { fileInputFromFile, fileInputValue, isFileUploadInput } from "@/lib/inputs";
import type { ContractInput, FileInputValue } from "@/types";

export function ContractInputControl({
  input,
  value,
  onChange,
}: {
  input: ContractInput;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [draggingFile, setDraggingFile] = useState(false);
  const id = `input-${input.name}`;
  const label = labelFor(input);
  const required = input.required ? "required" : "optional";

  function selectInputFile(file: File | undefined) {
    if (!file || !fileMatchesInputType(file, input.type)) return;
    onChange(fileInputFromFile(file));
  }

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

  if (isFileUploadInput(input)) {
    const fileValue = fileInputValue(value);
    const uploadType = uploadLabel(input.type);
    const UploadIcon = uploadIcon(input.type);
    return (
      <Field
        label={label}
        meta={
          <>
            {required} · {uploadType.toUpperCase()}
          </>
        }
      >
        <div className="file-input-control">
          <label
            className={`file-upload-button${draggingFile ? " is-dragging" : ""}`}
            htmlFor={id}
            onDragEnter={(event) => {
              event.preventDefault();
              setDraggingFile(true);
            }}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
              setDraggingFile(true);
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setDraggingFile(false);
              }
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDraggingFile(false);
              selectInputFile(event.dataTransfer.files?.[0]);
            }}
          >
            <UploadIcon size={16} />
            <span>{fileValue ? `Change or drop ${uploadType}` : `Choose or drop ${uploadType}`}</span>
            <input
              id={id}
              type="file"
              accept={acceptForInputType(input.type)}
              onChange={(event) => {
                selectInputFile(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </label>
          {fileValue ? (
            <FileInputPreview value={fileValue} type={input.type} onRemove={() => onChange(null)} />
          ) : (
            <p className="file-input-empty">Upload a {uploadType} for this workflow input.</p>
          )}
        </div>
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

function fileMatchesInputType(file: File, type: string) {
  if (type === "image") return file.type.startsWith("image/");
  if (type === "audio") return file.type.startsWith("audio/");
  if (type === "video") return file.type.startsWith("video/");
  return true;
}

function acceptForInputType(type: string) {
  if (type === "image") return "image/*";
  if (type === "audio") return "audio/*";
  if (type === "video") return "video/*";
  return undefined;
}

function uploadLabel(type: string) {
  if (type === "image") return "image";
  if (type === "audio") return "audio";
  if (type === "video") return "video";
  return "file";
}

function uploadIcon(type: string) {
  if (type === "image") return ImagePlus;
  if (type === "audio") return FileAudio;
  if (type === "video") return FileVideo;
  return FileUp;
}

function FileInputPreview({
  value,
  type,
  onRemove,
}: {
  value: FileInputValue;
  type: string;
  onRemove: () => void;
}) {
  if (type === "audio") {
    return (
      <div className="file-input-preview is-audio">
        <div className="file-input-preview-header">
          <strong>{value.filename}</strong>
          <button type="button" onClick={onRemove}>
            Remove
          </button>
        </div>
        <FilePreview value={value} type={type} />
      </div>
    );
  }

  return (
    <div className="file-input-preview">
      <FilePreview value={value} type={type} />
      <div>
        <strong>{value.filename}</strong>
        <button type="button" onClick={onRemove}>
          Remove
        </button>
      </div>
    </div>
  );
}

function FilePreview({ value, type }: { value: FileInputValue; type: string }) {
  if (type === "image") {
    return <img src={value.preview_url} alt="" />;
  }
  if (type === "audio") {
    return <audio src={value.preview_url} controls preload="metadata" />;
  }
  if (type === "video") {
    return <video src={value.preview_url} controls preload="metadata" />;
  }
  return (
    <span className="file-input-preview-icon">
      <FileUp size={18} />
    </span>
  );
}
