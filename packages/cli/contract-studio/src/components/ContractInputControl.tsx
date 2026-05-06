import { useState } from "react";
import { ImagePlus } from "lucide-react";
import { Field, NumberPicker, StudioSelect } from "@/app/components";
import { compactType, labelFor } from "@/lib/format";
import { imageInputFromFile, imageInputValue } from "@/lib/inputs";
import type { ContractInput } from "@/types";

export function ContractInputControl({
  input,
  value,
  onChange,
}: {
  input: ContractInput;
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const [draggingImage, setDraggingImage] = useState(false);
  const id = `input-${input.name}`;
  const label = labelFor(input);
  const required = input.required ? "required" : "optional";

  function selectImageFile(file: File | undefined) {
    if (!file || !file.type.startsWith("image/")) return;
    onChange(imageInputFromFile(file));
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

  if (input.type === "image") {
    const imageValue = imageInputValue(value);
    return (
      <Field
        label={label}
        meta={
          <>
            {required} · IMAGE
          </>
        }
      >
        <div className="image-input-control">
          <label
            className={`image-upload-button${draggingImage ? " is-dragging" : ""}`}
            htmlFor={id}
            onDragEnter={(event) => {
              event.preventDefault();
              setDraggingImage(true);
            }}
            onDragOver={(event) => {
              event.preventDefault();
              event.dataTransfer.dropEffect = "copy";
              setDraggingImage(true);
            }}
            onDragLeave={(event) => {
              if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
                setDraggingImage(false);
              }
            }}
            onDrop={(event) => {
              event.preventDefault();
              setDraggingImage(false);
              selectImageFile(event.dataTransfer.files?.[0]);
            }}
          >
            <ImagePlus size={16} />
            <span>{imageValue ? "Change or drop image" : "Choose or drop image"}</span>
            <input
              id={id}
              type="file"
              accept="image/*"
              onChange={(event) => {
                selectImageFile(event.target.files?.[0]);
                event.target.value = "";
              }}
            />
          </label>
          {imageValue ? (
            <div className="image-input-preview">
              <img src={imageValue.preview_url} alt="" />
              <div>
                <strong>{imageValue.filename}</strong>
                <button type="button" onClick={() => onChange(null)}>
                  Remove
                </button>
              </div>
            </div>
          ) : (
            <p className="image-input-empty">Upload an image for this workflow input.</p>
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
