export type ContractInput = {
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

export type ContractOutput = {
  name: string;
  type: string;
  display_name?: string;
  description?: string;
};

export type ContractSummary = {
  workflow: string;
  contract: string;
  display_name?: string;
  description?: string;
  inputs: ContractInput[];
  outputs: ContractOutput[];
};

export type ContractsResponse = {
  environment: string;
  contracts: ContractSummary[];
};

export type HealthResponse = {
  ok: boolean;
  environment: string;
  comfy_url: string;
  comfyui?: { available: boolean; error?: string };
};

export type RunIssue = {
  code: string;
  message: string;
  severity?: string;
  input_name?: string;
};

export type OutputArtifact = {
  filename?: string;
  subfolder?: string;
  type?: string;
  url?: string;
  width?: number;
  height?: number;
  raw?: unknown;
};

export type RunOutput = {
  name: string;
  type: string;
  node_id: string;
  artifacts: OutputArtifact[];
};

export type RunOutputSlot = {
  slot_id: string;
  run_id: string;
  contract?: string;
  contractWorkflow?: string;
  contractName?: string;
  outputName: string;
  type: "image" | "video" | "audio" | "json";
  status: "pending" | "running" | "done" | "empty" | "error" | "cancelled";
  promptId?: string;
  width?: number;
  height?: number;
  error?: string;
  rawResult?: RunResponse;
  createdAt: string;
  updatedAt?: string;
};

export type RunResponse = {
  status: string;
  run_id?: string;
  prompt_id?: string;
  issues?: RunIssue[];
  outputs?: RunOutput[];
  output_slots?: RunOutputSlot[];
  gallery_items?: GalleryItem[];
  error?: string;
  message?: string;
};

export type CancelRunResponse = {
  status: "cancelled";
  run_id: string;
  run?: Record<string, unknown> | null;
  output_slots?: RunOutputSlot[];
  gallery_items?: GalleryItem[];
  error?: string;
  message?: string;
};

export type GalleryItem = {
  id: string;
  run_id?: string;
  contract: string;
  contractWorkflow?: string;
  contractName?: string;
  promptId?: string;
  slotId?: string;
  output?: RunOutput;
  artifact?: OutputArtifact;
  filename?: string;
  outputName?: string;
  type: "image" | "video" | "audio" | "json";
  url?: string;
  status: "pending" | "done" | "error" | "cancelled";
  width: number;
  height: number;
  inputs?: Record<string, unknown>;
  rawResult?: RunResponse;
  error?: string;
  createdAt: string;
};

export type GalleryResponse = {
  state: "ephemeral" | "local" | string;
  gallery: "private" | "shared" | string;
  session_id: string;
  items: GalleryItem[];
};

export type GalleryDeleteResponse = {
  deleted: boolean;
};

export type GalleryPhoto = {
  src: string;
  width: number;
  height: number;
  key: string;
  item: GalleryItem;
};

export type FileInputValue = {
  file: File;
  preview_url: string;
  filename: string;
  mime_type: string;
  size: number;
};

export type FileRef = {
  kind: "file_ref";
  ref: string;
  filename: string;
  mime_type: string;
  size?: number;
};

export type UploadPrepareResponse = {
  kind: "upload_slot";
  upload_id: string;
  ref: string;
  upload_url: string;
  method: "PUT";
  headers?: Record<string, string>;
  file_ref: FileRef;
};
