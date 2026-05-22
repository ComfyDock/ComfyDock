# Constraints

Constraints tell uv that a package must stay within a particular version range.
Use them when two nodes or packages need help resolving together.

## Add Constraints

```bash
cg constraint add "opencv-python<5"
cg constraint add "numpy<2" "pillow>=10"
```

List constraints:

```bash
cg constraint list
```

Remove constraints:

```bash
cg constraint remove opencv-python
```

Constraints are stored as uv constraint dependency strings in the environment
manifest.

## When To Use Constraints

Use constraints when:

- two nodes require overlapping but incompatible versions
- a package released a breaking update
- CUDA or binary packages need a specific range
- you need stable behavior across team machines

Do not use constraints as the first answer to every conflict. Sometimes the
right fix is updating a node, removing a duplicate package, using an overlay for
local experiments, or separating incompatible workflows into different
environments.

## Constraints Vs Overlays

Use constraints for portable dependency policy that should follow the
environment.

Use overlays for machine-local or temporary dependency changes:

```bash
cg overlay create local-dev --local
cg overlay enable local-dev
```

## Validate

After changing constraints:

```bash
cg sync
cg status
```

If sync fails, use verbose output:

```bash
cg sync --verbose
```
