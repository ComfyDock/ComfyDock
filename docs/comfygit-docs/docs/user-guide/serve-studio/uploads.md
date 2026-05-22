# Uploads And File Refs

Workflow contracts can accept text, numbers, booleans, choices, and media files.
For media files, `cg serve` uses upload references instead of putting bytes
directly inside the run request.

## Why File Refs Exist

Run requests should stay small JSON control messages. Large images, audio, video,
or generic files are uploaded first, then referenced by an opaque `file_ref`.

That keeps the API predictable and avoids sending base64 blobs through every
contract run request.

## Upload Flow

Prepare an upload:

```bash
curl -X POST http://127.0.0.1:8190/uploads/prepare \
  -H 'content-type: application/json' \
  -d '{
    "filename": "input.png",
    "content_type": "image/png"
  }'
```

The response includes an upload URL, token, and `file_ref`.

Upload the bytes:

```bash
curl -X PUT 'http://127.0.0.1:8190/uploads/<upload_id>?token=<token>' \
  -H 'content-type: image/png' \
  --data-binary @input.png
```

Use the `file_ref` in the contract run:

```bash
curl -X POST \
  http://127.0.0.1:8190/contracts/my-workflow/default/run \
  -H 'content-type: application/json' \
  -d '{
    "inputs": {
      "input_image": {
        "file_ref": "upload:<opaque-ref>"
      }
    },
    "wait": true
  }'
```

## Plain String Media Inputs

For advanced callers, a plain string passed to a media input means "this file is
already available to ComfyUI by that input filename."

Most clients should prefer upload refs.

## Studio Handles This For You

The packaged Studio UI uses the same upload endpoints. When a user chooses a
file, Studio uploads it first and submits the resulting file ref in the run
request.

!!! note "Media placeholder"
    Add a screenshot or short clip of selecting an image input in Studio and
    seeing it attached to a workflow run.

## Related Guides

- [Serve workflows](serving-workflows.md)
- [Workflow contracts](../workflows/workflow-contracts.md)
