# Contract Studio Agent Notes

This directory is the shared ComfyGit Studio Vite/React frontend package. It is
consumed by local `cg serve` and by hosted Cloud published endpoints. The CLI
and Manager serve a built static copy from
`packages/studio-runtime/comfygit_studio/static/` through the shared
`comfygit-studio` Python runtime. Cloud should import or serve the same package
instead of maintaining a parallel playground UI.

## File Layout

- `src/main.tsx`: React bootstrap only. Do not put app logic here.
- `src/index.tsx`: package entrypoint for hosts embedding Studio.
- `src/App.tsx`: top-level Studio state and page composition. Keep detailed
  rendering and reusable behavior in components or `src/lib/`.
- `src/types.ts`: shared API and UI types for contracts, runs, uploads, and
  gallery items.
- `src/lib/`: pure helpers and frontend service functions.
  - `api.ts`: Studio API calls and upload transport.
  - `runtime-config.ts`: host-provided API base path and auth configuration.
  - `inputs.ts`: contract input defaults, normalization, and upload prep.
  - `format.ts`: display formatting, output typing, dimensions, and JSON
    redaction helpers.
  - `clipboard.ts`: clipboard helpers.
- `src/components/`: Contract Studio-specific UI components.
- `src/components/ui/`: shadcn-style reusable primitives.
- `src/app/components.tsx`: shared J-AI-Studio-derived primitives still used by
  the Studio, such as `Field`, `Media`, `NumberPicker`, `StudioSelect`, and
  `Tip`.
- `src/styles.css`: global Studio theme, layout, gallery, and viewer styling.

## Working Rules

- Reuse existing helpers in `src/lib/` before adding inline helpers to
  `App.tsx` or component files.
- Put reusable rendering in `src/components/`; keep `App.tsx` focused on
  state flow and layout composition.
- Put broadly reusable primitives in `src/components/ui/` only when they are
  genuinely general UI building blocks.
- Keep generated/static output changes intentional. Running `npm run build`
  rewrites files under `dist/static/`; release packaging copies that build into
  `packages/studio-runtime/comfygit_studio/static/`.
- If changing image/video/gallery behavior, check `GalleryTile`,
  `OutputViewer`, `Media`, and the gallery styles before creating a parallel
  implementation.
- If changing contract request behavior, check `src/lib/api.ts`,
  `src/lib/runtime-config.ts`, and `src/lib/inputs.ts` first.

## Validation

Run from this directory after frontend changes:

```bash
npm run build
```

For browser-facing changes, prefer testing through the Vite dev server at the
browser-reachable Tailscale host/port when it is already running.
