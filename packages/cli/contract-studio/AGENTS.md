# Contract Studio Agent Notes

This directory is a Vite/React frontend embedded in the ComfyGit CLI package.
It builds into `packages/cli/comfygit_cli/contract_studio_static/`, which is
served by `cg serve`.

## File Layout

- `src/main.tsx`: React bootstrap only. Do not put app logic here.
- `src/App.tsx`: top-level Studio state and page composition. Keep detailed
  rendering and reusable behavior in components or `src/lib/`.
- `src/types.ts`: shared API and UI types for contracts, runs, uploads, and
  gallery items.
- `src/lib/`: pure helpers and frontend service functions.
  - `api.ts`: `cg serve` API calls and upload transport.
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
  rewrites files under `../comfygit_cli/contract_studio_static/`.
- If changing image/video/gallery behavior, check `GalleryTile`,
  `OutputViewer`, `Media`, and the gallery styles before creating a parallel
  implementation.
- If changing contract request behavior, check `src/lib/api.ts` and
  `src/lib/inputs.ts` first.

## Validation

Run from this directory after frontend changes:

```bash
npm run build
```

For browser-facing changes, prefer testing through the Vite dev server at the
browser-reachable Tailscale host/port when it is already running.
