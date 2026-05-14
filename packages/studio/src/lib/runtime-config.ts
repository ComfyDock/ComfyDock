export type StudioRuntimeConfig = {
  apiBasePath: string;
  endpointName?: string;
  authMode?: "none" | "endpoint";
};

declare global {
  interface Window {
    __COMFYGIT_STUDIO_CONFIG__?: Partial<StudioRuntimeConfig>;
  }
}

const DEFAULT_CONFIG: StudioRuntimeConfig = {
  apiBasePath: "",
  authMode: "none",
};

let runtimeConfig: StudioRuntimeConfig = normalizeConfig(
  typeof window !== "undefined" ? window.__COMFYGIT_STUDIO_CONFIG__ : undefined,
);

export function configureStudioRuntime(config: Partial<StudioRuntimeConfig> | undefined) {
  runtimeConfig = normalizeConfig({ ...runtimeConfig, ...(config || {}) });
}

export function getStudioRuntimeConfig(): StudioRuntimeConfig {
  return runtimeConfig;
}

export function studioApiPath(path: string): string {
  if (/^https?:\/\//i.test(path)) return path;
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const base = normalizeBasePath(runtimeConfig.apiBasePath);
  if (!base) return normalizedPath;
  if (normalizedPath === base || normalizedPath.startsWith(`${base}/`)) {
    return normalizedPath;
  }
  return `${base}${normalizedPath}`;
}

function normalizeConfig(config: Partial<StudioRuntimeConfig> | undefined): StudioRuntimeConfig {
  return {
    ...DEFAULT_CONFIG,
    ...(config || {}),
    apiBasePath: normalizeBasePath(config?.apiBasePath || ""),
    authMode: config?.authMode === "endpoint" ? "endpoint" : "none",
  };
}

function normalizeBasePath(path: string): string {
  const trimmed = String(path || "").trim();
  if (!trimmed || trimmed === "/") return "";
  return `/${trimmed.replace(/^\/+|\/+$/g, "")}`;
}
