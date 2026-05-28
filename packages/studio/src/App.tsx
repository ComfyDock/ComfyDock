import { useCallback, useEffect, useMemo, useRef, useState, type UIEvent } from "react";
import { MasonryPhotoAlbum } from "react-photo-album";
import "react-photo-album/masonry.css";
import { Wand2 } from "lucide-react";
import { Field, StudioSelect } from "@/app/components";
import { ContractInputControl } from "@/components/ContractInputControl";
import { GalleryTile } from "@/components/GalleryTile";
import { OutputViewer } from "@/components/OutputViewer";
import { Button } from "@/components/ui/button";
import { ApiError, apiJson } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { getStudioRuntimeConfig } from "@/lib/runtime-config";
import {
  appendGalleryItems,
  columnCountForWidth,
  galleryItemsFromOutputs,
  galleryItemsFromSlots,
  galleryPhoto,
  mergeGalleryItems,
  normalizeGalleryItems,
  pendingGalleryItemsFromContract,
  reconcileGalleryItems,
  removeRunPendingItems,
  visibleGalleryItems,
} from "@/lib/gallery";
import { contractTitle, displayInputsForGallery, jsonBlock } from "@/lib/format";
import { inputDefaults, prepareSubmitInputs } from "@/lib/inputs";
import type {
  CancelRunResponse,
  ContractsResponse,
  GalleryDeleteResponse,
  GalleryItem,
  GalleryResponse,
  HealthResponse,
  RunIssue,
  RunResponse,
  StudioSessionResponse,
} from "@/types";

const GALLERY_INITIAL_BATCH = 72;
const GALLERY_BATCH_SIZE = 48;
const GALLERY_SPACING_PX = 7;
const GALLERY_LOAD_MORE_THRESHOLD_PX = 900;
const GALLERY_API_PAGE_SIZE = GALLERY_INITIAL_BATCH;

export function App() {
  const [contractsData, setContractsData] = useState<ContractsResponse | null>(null);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [selectedKey, setSelectedKey] = useState("");
  const [inputs, setInputs] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false);
  const [, setStatus] = useState("Ready");
  const [issues, setIssues] = useState<RunIssue[]>([]);
  const [gallery, setGallery] = useState<GalleryItem[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [rawResult, setRawResult] = useState<RunResponse | null>(null);
  const [cancellingRunId, setCancellingRunId] = useState<string | null>(null);
  const [galleryRenderCount, setGalleryRenderCount] = useState(GALLERY_INITIAL_BATCH);
  const [galleryCursor, setGalleryCursor] = useState<string | null>(null);
  const [galleryHasMore, setGalleryHasMore] = useState(false);
  const [galleryLoadingMore, setGalleryLoadingMore] = useState(false);
  const [studioSession, setStudioSession] = useState<StudioSessionResponse | null>(null);
  const [studioPasscode, setStudioPasscode] = useState("");
  const [studioAuthError, setStudioAuthError] = useState("");
  const [studioAuthBusy, setStudioAuthBusy] = useState(false);
  const galleryScrollRef = useRef<HTMLDivElement | null>(null);
  const endpointAuthEnabled = getStudioRuntimeConfig().authMode === "endpoint";

  const loadGallery = useCallback(async () => {
    const nextGallery = await apiJson<GalleryResponse>(`/gallery?limit=${GALLERY_API_PAGE_SIZE}`);
    setGallery((current) => reconcileGalleryItems(nextGallery.items || [], current));
    setGalleryCursor(nextGallery.next_cursor || null);
    setGalleryHasMore(Boolean(nextGallery.has_more && nextGallery.next_cursor));
  }, []);

  const loadNextGalleryPage = useCallback(async () => {
    if (!galleryCursor || galleryLoadingMore) return;
    setGalleryLoadingMore(true);
    try {
      const nextGallery = await apiJson<GalleryResponse>(
        `/gallery?limit=${GALLERY_BATCH_SIZE}&cursor=${encodeURIComponent(galleryCursor)}`,
      );
      setGallery((current) => appendGalleryItems(current, normalizeGalleryItems(nextGallery.items || [])));
      setGalleryCursor(nextGallery.next_cursor || null);
      setGalleryHasMore(Boolean(nextGallery.has_more && nextGallery.next_cursor));
      setGalleryRenderCount((current) => current + GALLERY_BATCH_SIZE);
    } finally {
      setGalleryLoadingMore(false);
    }
  }, [galleryCursor, galleryLoadingMore]);

  const loadStudioSession = useCallback(async () => {
    if (!endpointAuthEnabled) return null;
    const nextSession = await apiJson<StudioSessionResponse>("/studio-session");
    setStudioSession(nextSession);
    return nextSession;
  }, [endpointAuthEnabled]);

  useEffect(() => {
    void refresh();
  }, []);

  useEffect(() => {
    const hasPending = gallery.some((item) => item.status === "pending");
    if (!hasPending) return;
    const interval = window.setInterval(() => {
      void loadGallery();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [gallery, loadGallery]);

  const contracts = contractsData?.contracts || [];
  const selected = useMemo(
    () => contracts.find((item) => `${item.workflow}:${item.contract}` === selectedKey) || contracts[0],
    [contracts, selectedKey],
  );
  const activeKey = selected ? `${selected.workflow}:${selected.contract}` : "";
  const cancellableRunId = useMemo(
    () => gallery.find((item) => item.status === "pending" && item.run_id)?.run_id || null,
    [gallery],
  );
  const generationInProgress = busy || Boolean(cancellableRunId);

  useEffect(() => {
    if (!selected) return;
    setSelectedKey(`${selected.workflow}:${selected.contract}`);
    setInputs(inputDefaults(selected));
    setIssues([]);
    setRawResult(null);
  }, [selected?.workflow, selected?.contract]);

  const refresh = useCallback(async () => {
    setStatus("Loading contracts");
    try {
      const nextSession = await loadStudioSession();
      if (endpointAuthEnabled && !nextSession?.studio_session.authenticated) {
        setStatus("Studio locked");
        return;
      }
      const [nextContracts, nextHealth] = await Promise.all([
        apiJson<ContractsResponse>("/contracts"),
        apiJson<HealthResponse>("/health"),
      ]);
      setContractsData(nextContracts);
      setHealth(nextHealth);
      await loadGallery();
      setStatus("Ready");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not load contracts");
    }
  }, [endpointAuthEnabled, loadGallery, loadStudioSession]);

  const submitStudioPasscode = useCallback(async () => {
    const passcode = studioPasscode.trim();
    if (!passcode || studioAuthBusy) return;
    setStudioAuthBusy(true);
    setStudioAuthError("");
    try {
      const nextSession = await apiJson<StudioSessionResponse>("/studio-session", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ passcode }),
      });
      setStudioSession(nextSession);
      setStudioPasscode("");
      await refresh();
    } catch (error) {
      setStudioAuthError(error instanceof Error ? error.message : "Incorrect password.");
    } finally {
      setStudioAuthBusy(false);
    }
  }, [refresh, studioAuthBusy, studioPasscode]);

  const runSelected = useCallback(async () => {
    if (!selected || generationInProgress) return;
    setBusy(true);
    setIssues([]);
    setRawResult(null);
    setStatus("Uploading inputs");
    let submitInputs: Record<string, unknown>;
    try {
      submitInputs = await prepareSubmitInputs(selected, inputs);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Input upload failed";
      setStatus(message);
      setBusy(false);
      return;
    }
    setStatus("Submitting");
    const displayInputs = displayInputsForGallery(submitInputs);
    try {
      const result = await apiJson<RunResponse>(
        `/contracts/${encodeURIComponent(selected.workflow)}/${encodeURIComponent(selected.contract)}/run`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ inputs: submitInputs }),
        },
      );
      setRawResult(result);
      setIssues(result.issues || []);
      const nextItems = result.gallery_items?.length
        ? normalizeGalleryItems(result.gallery_items)
        : result.output_slots?.length
          ? galleryItemsFromSlots(result.output_slots, selected, displayInputs)
          : result.outputs?.length
            ? galleryItemsFromOutputs(result, selected, displayInputs)
            : pendingGalleryItemsFromContract(result, selected, displayInputs);
      if (nextItems.length) {
        setGallery((current) => mergeGalleryItems(nextItems, current));
      } else {
        void loadGallery();
      }
      setStatus(result.status === "completed" ? "Completed" : result.status);
    } catch (error) {
      const message = error instanceof Error ? error.message : "Generation failed";
      const errorData = error instanceof ApiError ? runResponseFromUnknown(error.data) : null;
      if (errorData?.issues?.length) {
        setIssues(errorData.issues);
      }
      if (errorData?.gallery_items?.length) {
        setRawResult(errorData);
        const errorItems = normalizeGalleryItems(errorData.gallery_items);
        setGallery((current) => mergeGalleryItems(errorItems, current));
        setStatus(message);
        return;
      }
      setStatus(message);
      void loadGallery();
    } finally {
      setBusy(false);
    }
  }, [generationInProgress, inputs, loadGallery, selected]);

  useEffect(() => {
    function handleShortcut(event: KeyboardEvent) {
      if (event.defaultPrevented || event.repeat || event.isComposing) return;
      if (!event.ctrlKey || event.key !== "Enter") return;
      event.preventDefault();
      void runSelected();
    }

    window.addEventListener("keydown", handleShortcut);
    return () => window.removeEventListener("keydown", handleShortcut);
  }, [runSelected]);

  const copyGalleryItem = useCallback(async (item: GalleryItem) => {
    if (!item.url) {
      await copyText(jsonBlock(item.artifact?.raw || item.artifact || item.inputs || {}));
      return;
    }
    if (item.type !== "image") {
      await copyText(new URL(item.url, window.location.href).href);
      return;
    }
    try {
      const response = await fetch(item.url);
      const blob = await response.blob();
      const type = blob.type || "image/png";
      await navigator.clipboard.write([new ClipboardItem({ [type]: blob })]);
    } catch {
      await copyText(new URL(item.url, window.location.href).href);
    }
  }, []);

  const deleteGalleryItem = useCallback((item: GalleryItem) => {
    setGallery((current) => current.filter((candidate) => candidate.id !== item.id));
    setActiveId((current) => (current === item.id ? null : current));
    if (!item.id.startsWith("pending-")) {
      void apiJson<GalleryDeleteResponse>(`/gallery/${encodeURIComponent(item.id)}`, { method: "DELETE" }).catch(() => {
        void refresh();
      });
    }
  }, [refresh]);

  const visibleGallery = useMemo(() => visibleGalleryItems(gallery), [gallery]);
  const renderedGallery = useMemo(() => visibleGallery.slice(0, galleryRenderCount), [galleryRenderCount, visibleGallery]);
  const renderedPhotos = useMemo(() => renderedGallery.map(galleryPhoto), [renderedGallery]);
  const hasMoreGallery = renderedGallery.length < visibleGallery.length || galleryHasMore;
  const activeItem = visibleGallery.find((item) => item.id === activeId) || null;
  const activeIndex = activeItem ? visibleGallery.findIndex((item) => item.id === activeItem.id) : -1;
  const proxyExecutorConfigured = health?.executor === "proxy" && health.proxy?.configured !== false;
  const healthReady = proxyExecutorConfigured || Boolean(health?.comfyui?.available);
  const healthLabel = !health
    ? "Loading"
    : proxyExecutorConfigured
      ? "Endpoint configured"
      : health.comfyui?.available
        ? "ComfyUI online"
        : "ComfyUI unavailable";
  const studioGate = studioSession?.studio_session;
  const studioLocked = endpointAuthEnabled && studioGate && !studioGate.authenticated;
  const studioDisabled = endpointAuthEnabled && studioGate && !studioGate.studio_enabled;

  useEffect(() => {
    setGalleryRenderCount((current) =>
      Math.min(Math.max(GALLERY_INITIAL_BATCH, current), Math.max(GALLERY_INITIAL_BATCH, visibleGallery.length)),
    );
  }, [visibleGallery.length]);

  const loadMoreGalleryItems = useCallback(() => {
    if (renderedGallery.length < visibleGallery.length) {
      setGalleryRenderCount((current) => Math.min(current + GALLERY_BATCH_SIZE, visibleGallery.length));
      return;
    }
    void loadNextGalleryPage();
  }, [loadNextGalleryPage, renderedGallery.length, visibleGallery.length]);

  const onGalleryScroll = useCallback(
    (event: UIEvent<HTMLDivElement>) => {
      if (!hasMoreGallery) return;
      const target = event.currentTarget;
      const remaining = target.scrollHeight - target.scrollTop - target.clientHeight;
      if (remaining < GALLERY_LOAD_MORE_THRESHOLD_PX) {
        loadMoreGalleryItems();
      }
    },
    [hasMoreGallery, loadMoreGalleryItems],
  );

  const cancelActiveRun = useCallback(async () => {
    if (!cancellableRunId || cancellingRunId) return;
    setCancellingRunId(cancellableRunId);
    setStatus("Cancelling");
    try {
      const result = await apiJson<CancelRunResponse>(`/runs/${encodeURIComponent(cancellableRunId)}/cancel`, {
        method: "POST",
      });
      const nextItems = normalizeGalleryItems(result.gallery_items || []);
      if (nextItems.length) {
        setGallery((current) => mergeGalleryItems(nextItems, removeRunPendingItems(current, cancellableRunId)));
      } else {
        setGallery((current) => removeRunPendingItems(current, cancellableRunId));
      }
      setStatus("Cancelled");
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "Could not cancel generation");
      await loadGallery();
    } finally {
      setCancellingRunId(null);
    }
  }, [cancellableRunId, cancellingRunId, loadGallery]);

  function moveActive(delta: number) {
    if (activeIndex < 0 || !visibleGallery.length) return;
    const next = visibleGallery[(activeIndex + delta + visibleGallery.length) % visibleGallery.length];
    setActiveId(next.id);
  }

  return (
    <main className="studio-shell">
      <section className="gallery-stage" aria-label="Outputs">
        <header className="top-bar">
          <div>
            <p className="eyebrow">ComfyGit Studio</p>
            <h1>{contractsData?.environment || "Environment"}</h1>
          </div>
          <div className="health-pill" data-ready={healthReady || undefined}>
            <span>{healthLabel}</span>
          </div>
        </header>

        <div ref={galleryScrollRef} className="gallery-scroll" onScroll={onGalleryScroll}>
          {visibleGallery.length ? (
            <section className="gallery" aria-label="Generated outputs">
              <MasonryPhotoAlbum
                photos={renderedPhotos}
                spacing={GALLERY_SPACING_PX}
                padding={0}
                columns={columnCountForWidth}
                render={{
                  photo: (_, { photo, width, height }) => (
                    <GalleryTile
                      key={photo.item.id}
                      item={photo.item}
                      width={width}
                      height={height}
                      onOpen={setActiveId}
                      onCopy={copyGalleryItem}
                      onDelete={deleteGalleryItem}
                    />
                  ),
                }}
              />
              {hasMoreGallery ? (
                <button
                  className="gallery-load-more"
                  type="button"
                  onClick={loadMoreGalleryItems}
                  disabled={galleryLoadingMore}
                >
                  {galleryLoadingMore ? "Loading..." : "Load more"}
                </button>
              ) : null}
            </section>
          ) : (
            <div className="empty-stage">
              <p>Run a contract to collect outputs here.</p>
            </div>
          )}
        </div>
      </section>

      <aside className="control-panel">
        <div className="brand-row">
          <div>
            <p className="eyebrow">Contract</p>
            <h2>{contracts.length} available</h2>
          </div>
          <Button type="button" variant="tertiary" size="sm" onClick={refresh} disabled={busy}>
            Refresh
          </Button>
        </div>

        {studioDisabled ? (
          <section className="runner-card">
            <p>Studio is disabled.</p>
          </section>
        ) : studioLocked ? (
          <StudioAuthGate
            mode={studioGate.studio_auth_mode}
            passcode={studioPasscode}
            error={studioAuthError}
            busy={studioAuthBusy}
            onPasscodeChange={setStudioPasscode}
            onSubmit={() => void submitStudioPasscode()}
          />
        ) : contracts.length ? (
          <section className="contract-picker" aria-label="Select contract">
            <Field label="Workflow contract">
              <StudioSelect
                value={activeKey}
                disabled={generationInProgress}
                onChange={setSelectedKey}
                options={contracts.map((contract) => {
                  const key = `${contract.workflow}:${contract.contract}`;
                  return { label: contractTitle(contract), value: key };
                })}
              />
            </Field>
            {selected?.description ? <p className="description">{selected.description}</p> : null}
          </section>
        ) : null}

        {!studioLocked && !studioDisabled && selected ? (
          <section className="runner-card">
            <div className="input-stack">
              {selected.inputs.map((input) => (
                <ContractInputControl
                  key={input.name}
                  input={input}
                  value={inputs[input.name]}
                  onChange={(value) => setInputs((current) => ({ ...current, [input.name]: value }))}
                />
              ))}
            </div>

            {issues.length ? (
              <div className="issue-list">
                {issues.map((issue, index) => (
                  <p key={`${issue.code}-${index}`}>{issue.message}</p>
                ))}
              </div>
            ) : null}

            <Button
              type="button"
              className="generate-button"
              onClick={runSelected}
              disabled={generationInProgress}
              loading={generationInProgress}
              leadingIcon={Wand2}
            >
              {generationInProgress ? "Generating..." : "Generate"}
            </Button>
            {cancellableRunId ? (
              <Button
                type="button"
                variant="tertiary"
                className="cancel-generation-button"
                onClick={cancelActiveRun}
                disabled={Boolean(cancellingRunId)}
                loading={cancellingRunId === cancellableRunId}
              >
                Cancel generation
              </Button>
            ) : null}
          </section>
        ) : !studioLocked && !studioDisabled ? (
          <section className="runner-card">
            <p>No contracts found in this environment.</p>
          </section>
        ) : null}

        {rawResult && !visibleGallery.length ? (
          <section className="raw-card">
            <p className="eyebrow">Raw result</p>
            <pre>{JSON.stringify(rawResult, null, 2)}</pre>
          </section>
        ) : null}
      </aside>

      {activeItem ? (
        <OutputViewer
          item={activeItem}
          hasNeighbors={visibleGallery.length > 1}
          onClose={() => setActiveId(null)}
          onMove={moveActive}
          onCopy={copyGalleryItem}
          onDelete={deleteGalleryItem}
        />
      ) : null}
    </main>
  );
}

function StudioAuthGate({
  mode,
  passcode,
  error,
  busy,
  onPasscodeChange,
  onSubmit,
}: {
  mode: string;
  passcode: string;
  error: string;
  busy: boolean;
  onPasscodeChange: (value: string) => void;
  onSubmit: () => void;
}) {
  if (mode !== "passcode") {
    return (
      <section className="runner-card">
        <p>Studio access requires an owner launch session.</p>
      </section>
    );
  }
  return (
    <section className="runner-card">
      <form
        className="studio-auth-form"
        onSubmit={(event) => {
          event.preventDefault();
          onSubmit();
        }}
      >
        <div>
          <p className="eyebrow">Studio Access</p>
          <h2>Enter password</h2>
        </div>
        <input
          type="password"
          value={passcode}
          onChange={(event) => onPasscodeChange(event.target.value)}
          autoComplete="current-password"
          autoFocus
        />
        {error ? <p className="auth-error">{error}</p> : null}
        <Button type="submit" className="generate-button" disabled={busy || !passcode.trim()} loading={busy}>
          Enter Studio
        </Button>
      </form>
    </section>
  );
}

function runResponseFromUnknown(value: unknown): RunResponse | null {
  if (!value || typeof value !== "object") return null;
  return value as RunResponse;
}
