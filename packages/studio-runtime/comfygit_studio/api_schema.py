"""OpenAPI document for the public ComfyGit Studio contract API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

STUDIO_CONTRACT_API_VERSION = "1.0.0"
STUDIO_CONTRACT_API_TITLE = "ComfyGit Studio Contract API"

PUBLIC_STUDIO_API_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/openapi.json"),
    ("GET", "/health"),
    ("GET", "/contracts"),
    ("GET", "/contracts/{workflow}/{contract}"),
    ("POST", "/uploads/prepare"),
    ("PUT", "/uploads/{upload_id}"),
    ("GET", "/uploads/{upload_id}/status"),
    ("POST", "/contracts/{workflow}/{contract}/run"),
    ("GET", "/runs"),
    ("GET", "/runs/{run_id}"),
    ("POST", "/runs/{run_id}/cancel"),
    ("GET", "/gallery"),
    ("DELETE", "/gallery/{item_id}"),
    ("GET", "/outputs/view"),
)


def studio_contract_api_openapi() -> dict[str, Any]:
    """Return the versioned public OpenAPI document for the Studio contract API."""

    return {
        "openapi": "3.1.0",
        "info": {
            "title": STUDIO_CONTRACT_API_TITLE,
            "version": STUDIO_CONTRACT_API_VERSION,
            "description": (
                "Public contract-shaped API used by cg serve, Manager embedded Studio, "
                "and future hosted ComfyGit endpoints."
            ),
        },
        "servers": [{"url": "/", "description": "Mounted Studio runtime API base path"}],
        "paths": _paths(),
        "components": {"schemas": _schemas(), "parameters": _parameters()},
    }


def write_openapi(path: Path) -> None:
    """Write the generated OpenAPI document to disk."""

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(studio_contract_api_openapi(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _paths() -> dict[str, Any]:
    return {
        "/openapi.json": {
            "get": {
                "summary": "Return the Studio contract API OpenAPI document",
                "operationId": "getOpenApi",
                "responses": {
                    "200": {
                        "description": "OpenAPI document",
                        "content": {"application/json": {"schema": {"type": "object"}}},
                    }
                },
            }
        },
        "/health": {
            "get": {
                "summary": "Return Studio runtime and executor health",
                "operationId": "getHealth",
                "parameters": [{"$ref": "#/components/parameters/checkProxy"}],
                "responses": _json_response("Health response", "HealthResponse"),
            }
        },
        "/contracts": {
            "get": {
                "summary": "List available workflow contracts",
                "operationId": "listContracts",
                "responses": _json_response("Contracts response", "ContractsResponse"),
            }
        },
        "/contracts/{workflow}/{contract}": {
            "get": {
                "summary": "Return one workflow contract",
                "operationId": "getContract",
                "parameters": [
                    {"$ref": "#/components/parameters/workflow"},
                    {"$ref": "#/components/parameters/contract"},
                ],
                "responses": _json_response("Contract response", "ContractSummary"),
            }
        },
        "/uploads/prepare": {
            "post": {
                "summary": "Prepare a media upload slot",
                "operationId": "prepareUpload",
                "requestBody": _json_body("UploadPrepareRequest"),
                "responses": {
                    "200": _json_content("Upload slot", "UploadSlotResponse"),
                    "400": _json_content("Bad request", "ErrorResponse"),
                },
            }
        },
        "/uploads/{upload_id}": {
            "put": {
                "summary": "Upload bytes to a prepared slot",
                "operationId": "putUpload",
                "parameters": [
                    {"$ref": "#/components/parameters/uploadId"},
                    {"$ref": "#/components/parameters/uploadToken"},
                ],
                "requestBody": {
                    "required": True,
                    "content": {"application/octet-stream": {"schema": {"type": "string", "format": "binary"}}},
                },
                "responses": {
                    "200": _json_content("Upload ready", "UploadStatusResponse"),
                    "403": _json_content("Forbidden", "ErrorResponse"),
                    "404": _json_content("Unknown upload", "ErrorResponse"),
                    "413": _json_content("Upload too large", "ErrorResponse"),
                },
            }
        },
        "/uploads/{upload_id}/status": {
            "get": {
                "summary": "Return upload status and file reference",
                "operationId": "getUploadStatus",
                "parameters": [{"$ref": "#/components/parameters/uploadId"}],
                "responses": {
                    "200": _json_content("Upload status", "UploadStatusResponse"),
                    "404": _json_content("Unknown upload", "ErrorResponse"),
                },
            }
        },
        "/contracts/{workflow}/{contract}/run": {
            "post": {
                "summary": "Start a workflow contract run",
                "operationId": "runContract",
                "parameters": [
                    {"$ref": "#/components/parameters/workflow"},
                    {"$ref": "#/components/parameters/contract"},
                ],
                "requestBody": _json_body("RunRequest"),
                "responses": {
                    "200": _json_content("Run response", "RunResponse"),
                    "400": _json_content("Invalid request", "RunResponse"),
                    "413": _json_content("Request too large", "ErrorResponse"),
                    "502": _json_content("Executor unavailable", "RunResponse"),
                    "504": _json_content("Run timed out", "RunResponse"),
                },
            }
        },
        "/runs": {
            "get": {
                "summary": "List run records",
                "operationId": "listRuns",
                "parameters": [{"$ref": "#/components/parameters/activeRuns"}],
                "responses": _json_response("Runs response", "RunsResponse"),
            }
        },
        "/runs/{run_id}": {
            "get": {
                "summary": "Return one run record, output slots, and gallery items",
                "operationId": "getRun",
                "parameters": [{"$ref": "#/components/parameters/runId"}],
                "responses": {
                    "200": _json_content("Run details", "RunDetailsResponse"),
                    "404": _json_content("Unknown run", "ErrorResponse"),
                },
            }
        },
        "/runs/{run_id}/cancel": {
            "post": {
                "summary": "Cancel a running contract run",
                "operationId": "cancelRun",
                "parameters": [{"$ref": "#/components/parameters/runId"}],
                "responses": {
                    "200": _json_content("Cancelled run response", "CancelRunResponse"),
                    "400": _json_content("Run cannot be cancelled", "ErrorResponse"),
                    "404": _json_content("Unknown run", "ErrorResponse"),
                },
            }
        },
        "/gallery": {
            "get": {
                "summary": "List gallery items for the current Studio session",
                "operationId": "listGallery",
                "parameters": [
                    {"$ref": "#/components/parameters/galleryLimit"},
                    {"$ref": "#/components/parameters/galleryCursor"},
                ],
                "responses": {
                    "200": _json_content("Gallery response", "GalleryResponse"),
                    "400": _json_content("Invalid pagination request", "ErrorResponse"),
                },
            }
        },
        "/gallery/{item_id}": {
            "delete": {
                "summary": "Delete one gallery item from the current session",
                "operationId": "deleteGalleryItem",
                "parameters": [{"$ref": "#/components/parameters/itemId"}],
                "responses": {
                    "200": _json_content("Delete response", "GalleryDeleteResponse"),
                    "404": _json_content("Gallery item was not found", "GalleryDeleteResponse"),
                },
            }
        },
        "/outputs/view": {
            "get": {
                "summary": "Fetch a generated output artifact",
                "operationId": "viewOutput",
                "parameters": [
                    {"$ref": "#/components/parameters/serveArtifact"},
                    {"$ref": "#/components/parameters/filename"},
                    {"$ref": "#/components/parameters/subfolder"},
                    {"$ref": "#/components/parameters/outputType"},
                ],
                "responses": {
                    "200": {"description": "Output bytes"},
                    "400": _json_content("Bad request", "ErrorResponse"),
                    "404": _json_content("Output not found", "ErrorResponse"),
                    "502": _json_content("ComfyUI unavailable", "ErrorResponse"),
                },
            }
        },
    }


def _schemas() -> dict[str, Any]:
    freeform = {"type": "object", "additionalProperties": True}
    return {
        "ErrorResponse": {
            "type": "object",
            "properties": {"error": {"type": "string"}, "message": {"type": "string"}},
            "additionalProperties": True,
        },
        "HealthResponse": {
            "type": "object",
            "required": ["ok", "environment", "comfy_url"],
            "properties": {
                "ok": {"type": "boolean"},
                "environment": {"type": "string"},
                "environment_ref": freeform,
                "comfy_url": {"type": "string"},
                "executor": {"type": "string"},
                "comfyui": freeform,
                "proxy": freeform,
                "proxy_environment_ref_match": {"type": ["boolean", "null"]},
            },
            "additionalProperties": True,
        },
        "ContractInput": {
            "type": "object",
            "required": ["name", "type"],
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string"},
                "required": {"type": "boolean"},
                "display_name": {"type": "string"},
                "ui_control": {"type": "string", "enum": ["input", "textarea"]},
                "default": {},
                "min": {"type": "number"},
                "max": {"type": "number"},
                "step": {"type": "number"},
                "enum_values": {"type": "array", "items": {"type": "string"}},
                "description": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "ContractOutput": {
            "type": "object",
            "required": ["name", "type"],
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string"},
                "display_name": {"type": "string"},
                "description": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "ContractSummary": {
            "type": "object",
            "required": ["workflow", "contract", "inputs", "outputs"],
            "properties": {
                "workflow": {"type": "string"},
                "contract": {"type": "string"},
                "display_name": {"type": "string"},
                "description": {"type": "string"},
                "inputs": {"type": "array", "items": {"$ref": "#/components/schemas/ContractInput"}},
                "outputs": {"type": "array", "items": {"$ref": "#/components/schemas/ContractOutput"}},
            },
            "additionalProperties": True,
        },
        "ContractsResponse": {
            "type": "object",
            "required": ["environment", "contracts"],
            "properties": {
                "environment": {"type": "string"},
                "contracts": {"type": "array", "items": {"$ref": "#/components/schemas/ContractSummary"}},
            },
        },
        "FileRef": {
            "type": "object",
            "required": ["kind", "ref", "filename", "mime_type"],
            "properties": {
                "kind": {"type": "string", "const": "file_ref"},
                "ref": {"type": "string"},
                "filename": {"type": "string"},
                "mime_type": {"type": "string"},
                "size": {"type": "integer"},
            },
        },
        "UploadPrepareRequest": {
            "type": "object",
            "required": ["filename"],
            "properties": {
                "filename": {"type": "string"},
                "mime_type": {"type": "string"},
                "size": {"type": "integer", "minimum": 0},
            },
            "additionalProperties": True,
        },
        "UploadSlotResponse": {
            "type": "object",
            "required": ["kind", "upload_id", "ref", "upload_url", "method", "destination", "file_ref"],
            "properties": {
                "kind": {"type": "string", "const": "upload_slot"},
                "upload_id": {"type": "string"},
                "ref": {"type": "string"},
                "upload_url": {"type": "string"},
                "method": {"type": "string", "const": "PUT"},
                "headers": freeform,
                "destination": {"type": "string"},
                "max_size": {"type": "integer"},
                "file_ref": {"$ref": "#/components/schemas/FileRef"},
            },
        },
        "UploadStatusResponse": {
            "type": "object",
            "required": ["status", "file_ref"],
            "properties": {
                "status": {"type": "string"},
                "file_ref": {"$ref": "#/components/schemas/FileRef"},
            },
        },
        "RunIssue": {
            "type": "object",
            "required": ["code", "message"],
            "properties": {
                "code": {"type": "string"},
                "message": {"type": "string"},
                "severity": {"type": "string"},
                "input_name": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "OutputArtifact": {
            "type": "object",
            "properties": {
                "filename": {"type": "string"},
                "subfolder": {"type": "string"},
                "type": {"type": "string"},
                "url": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "raw": {},
            },
            "additionalProperties": True,
        },
        "RunOutput": {
            "type": "object",
            "required": ["name", "type", "artifacts"],
            "properties": {
                "name": {"type": "string"},
                "type": {"type": "string"},
                "node_id": {"type": "string"},
                "artifacts": {"type": "array", "items": {"$ref": "#/components/schemas/OutputArtifact"}},
            },
            "additionalProperties": True,
        },
        "RunOutputSlot": {
            "type": "object",
            "required": ["slot_id", "run_id", "outputName", "type", "status", "createdAt"],
            "properties": {
                "slot_id": {"type": "string"},
                "run_id": {"type": "string"},
                "contract": {"type": "string"},
                "contractWorkflow": {"type": "string"},
                "contractName": {"type": "string"},
                "outputName": {"type": "string"},
                "type": {"type": "string", "enum": ["image", "video", "audio", "json"]},
                "status": {"type": "string"},
                "promptId": {"type": "string"},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "error": {"type": "string"},
                "rawResult": freeform,
                "createdAt": {"type": "string"},
                "updatedAt": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "GalleryItem": {
            "type": "object",
            "required": ["id", "contract", "status", "type", "createdAt"],
            "properties": {
                "id": {"type": "string"},
                "run_id": {"type": "string"},
                "contract": {"type": "string"},
                "contractWorkflow": {"type": "string"},
                "contractName": {"type": "string"},
                "promptId": {"type": "string"},
                "slotId": {"type": "string"},
                "filename": {"type": "string"},
                "outputName": {"type": "string"},
                "type": {"type": "string", "enum": ["image", "video", "audio", "json"]},
                "url": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "done", "error", "cancelled"]},
                "width": {"type": "integer"},
                "height": {"type": "integer"},
                "inputs": freeform,
                "artifact": freeform,
                "rawResult": freeform,
                "error": {"type": "string"},
                "createdAt": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "GalleryResponse": {
            "type": "object",
            "required": ["state", "gallery", "session_id", "items", "has_more"],
            "properties": {
                "state": {"type": "string"},
                "gallery": {"type": "string"},
                "session_id": {"type": "string"},
                "items": {"type": "array", "items": {"$ref": "#/components/schemas/GalleryItem"}},
                "next_cursor": {"type": ["string", "null"]},
                "has_more": {"type": "boolean"},
                "limit": {"type": ["integer", "null"]},
            },
        },
        "RunRequest": {
            "type": "object",
            "properties": {
                "inputs": freeform,
                "wait": {"type": "boolean"},
                "timeout_seconds": {"type": "number"},
                "poll_interval_seconds": {"type": "number"},
            },
            "additionalProperties": True,
        },
        "RunResponse": {
            "type": "object",
            "required": ["status"],
            "properties": {
                "id": {"type": "string"},
                "status": {"type": "string"},
                "run_id": {"type": "string"},
                "prompt_id": {"type": "string"},
                "issues": {"type": "array", "items": {"$ref": "#/components/schemas/RunIssue"}},
                "outputs": {"type": "array", "items": {"$ref": "#/components/schemas/RunOutput"}},
                "output_slots": {"type": "array", "items": {"$ref": "#/components/schemas/RunOutputSlot"}},
                "gallery_items": {"type": "array", "items": {"$ref": "#/components/schemas/GalleryItem"}},
                "error": {"type": "string"},
                "message": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "RunsResponse": {
            "type": "object",
            "required": ["state", "session_id", "runs"],
            "properties": {
                "state": {"type": "string"},
                "session_id": {"type": "string"},
                "runs": {"type": "array", "items": {"$ref": "#/components/schemas/RunResponse"}},
            },
        },
        "RunDetailsResponse": {
            "type": "object",
            "required": ["state", "session_id", "run", "output_slots", "gallery_items"],
            "properties": {
                "state": {"type": "string"},
                "session_id": {"type": "string"},
                "run": {"$ref": "#/components/schemas/RunResponse"},
                "output_slots": {"type": "array", "items": {"$ref": "#/components/schemas/RunOutputSlot"}},
                "gallery_items": {"type": "array", "items": {"$ref": "#/components/schemas/GalleryItem"}},
            },
        },
        "CancelRunResponse": {
            "type": "object",
            "required": ["status", "run_id"],
            "properties": {
                "status": {"type": "string", "const": "cancelled"},
                "run_id": {"type": "string"},
                "run": {"oneOf": [{"$ref": "#/components/schemas/RunResponse"}, {"type": "null"}]},
                "output_slots": {"type": "array", "items": {"$ref": "#/components/schemas/RunOutputSlot"}},
                "gallery_items": {"type": "array", "items": {"$ref": "#/components/schemas/GalleryItem"}},
                "error": {"type": "string"},
                "message": {"type": "string"},
            },
            "additionalProperties": True,
        },
        "GalleryDeleteResponse": {
            "type": "object",
            "required": ["deleted"],
            "properties": {"deleted": {"type": "boolean"}},
        },
    }


def _parameters() -> dict[str, Any]:
    return {
        "workflow": {"name": "workflow", "in": "path", "required": True, "schema": {"type": "string"}},
        "contract": {"name": "contract", "in": "path", "required": True, "schema": {"type": "string"}},
        "uploadId": {"name": "upload_id", "in": "path", "required": True, "schema": {"type": "string"}},
        "uploadToken": {"name": "token", "in": "query", "required": True, "schema": {"type": "string"}},
        "runId": {"name": "run_id", "in": "path", "required": True, "schema": {"type": "string"}},
        "itemId": {"name": "item_id", "in": "path", "required": True, "schema": {"type": "string"}},
        "activeRuns": {"name": "active", "in": "query", "schema": {"type": "boolean"}},
        "checkProxy": {"name": "check_proxy", "in": "query", "schema": {"type": "boolean"}},
        "galleryLimit": {
            "name": "limit",
            "in": "query",
            "schema": {"type": "integer", "minimum": 1, "maximum": 200},
        },
        "galleryCursor": {"name": "cursor", "in": "query", "schema": {"type": "string"}},
        "serveArtifact": {"name": "serve_artifact", "in": "query", "schema": {"type": "string"}},
        "filename": {"name": "filename", "in": "query", "schema": {"type": "string"}},
        "subfolder": {"name": "subfolder", "in": "query", "schema": {"type": "string"}},
        "outputType": {"name": "type", "in": "query", "schema": {"type": "string"}},
    }


def _json_response(description: str, schema_name: str) -> dict[str, Any]:
    return {"200": _json_content(description, schema_name)}


def _json_content(description: str, schema_name: str) -> dict[str, Any]:
    return {
        "description": description,
        "content": {
            "application/json": {
                "schema": {"$ref": f"#/components/schemas/{schema_name}"},
            }
        },
    }


def _json_body(schema_name: str) -> dict[str, Any]:
    return {
        "required": True,
        "content": {
            "application/json": {
                "schema": {"$ref": f"#/components/schemas/{schema_name}"},
            }
        },
    }
