# ComfyGit Studio Runtime

`comfygit-studio` owns the shared contract-serving runtime used by `cg serve`
and embedded ComfyGit Manager Studio routes.

It is intentionally separate from `comfygit-core`: core owns environment and
contract domain semantics, while this package owns HTTP routing, Studio static
asset serving, upload handling, run/gallery state, and ComfyUI API execution.
