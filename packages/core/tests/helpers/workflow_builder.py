"""Helpers for building test workflow JSON data."""
from typing import Any


class WorkflowBuilder:
    """Fluent builder for ComfyUI workflow JSON."""

    def __init__(self):
        self.nodes = []
        self.links = []
        self.next_node_id = 1
        self.next_link_id = 1

    def add_checkpoint_loader(self, checkpoint_file: str) -> "WorkflowBuilder":
        """Add CheckpointLoaderSimple node."""
        node = {
            "id": str(self.next_node_id),
            "type": "CheckpointLoaderSimple",
            "pos": [100 + len(self.nodes) * 50, 100],
            "size": [315, 98],
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "outputs": [
                {"name": "MODEL", "type": "MODEL", "links": []},
                {"name": "CLIP", "type": "CLIP", "links": []},
                {"name": "VAE", "type": "VAE", "links": []}
            ],
            "properties": {},
            "widgets_values": [checkpoint_file]
        }
        self.nodes.append(node)
        self.next_node_id += 1
        return self

    def add_lora_loader(self, lora_file: str, strength: float = 1.0) -> "WorkflowBuilder":
        """Add LoraLoader node."""
        node = {
            "id": str(self.next_node_id),
            "type": "LoraLoader",
            "pos": [100 + len(self.nodes) * 50, 200],
            "size": [315, 126],
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "inputs": [
                {"name": "model", "type": "MODEL", "link": None},
                {"name": "clip", "type": "CLIP", "link": None}
            ],
            "outputs": [
                {"name": "MODEL", "type": "MODEL", "links": []},
                {"name": "CLIP", "type": "CLIP", "links": []}
            ],
            "properties": {},
            "widgets_values": [lora_file, strength, strength]
        }
        self.nodes.append(node)
        self.next_node_id += 1
        return self

    def add_clip_loader(self, clip_file: str) -> "WorkflowBuilder":
        """Add CLIPLoader node."""
        node = {
            "id": str(self.next_node_id),
            "type": "CLIPLoader",
            "pos": [100 + len(self.nodes) * 50, 250],
            "size": [315, 58],
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "outputs": [
                {"name": "CLIP", "type": "CLIP", "links": []}
            ],
            "properties": {},
            "widgets_values": [clip_file]
        }
        self.nodes.append(node)
        self.next_node_id += 1
        return self

    def add_unet_loader(self, unet_file: str) -> "WorkflowBuilder":
        """Add UNETLoader node."""
        node = {
            "id": str(self.next_node_id),
            "type": "UNETLoader",
            "pos": [100 + len(self.nodes) * 50, 300],
            "size": [315, 82],
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "outputs": [
                {"name": "MODEL", "type": "MODEL", "links": []}
            ],
            "properties": {},
            "widgets_values": [unet_file]
        }
        self.nodes.append(node)
        self.next_node_id += 1
        return self

    def add_custom_node(self, node_type: str, widgets: list[Any] | None = None) -> "WorkflowBuilder":
        """Add custom node with specified type."""
        node = {
            "id": str(self.next_node_id),
            "type": node_type,
            "pos": [100 + len(self.nodes) * 50, 300],
            "size": [200, 100],
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "properties": {},
            "widgets_values": widgets or []
        }
        self.nodes.append(node)
        self.next_node_id += 1
        return self

    def add_builtin_node(self, node_type: str, widgets: list[Any] | None = None) -> "WorkflowBuilder":
        """Add builtin ComfyUI node."""
        node = {
            "id": str(self.next_node_id),
            "type": node_type,
            "pos": [100 + len(self.nodes) * 50, 400],
            "size": [200, 100],
            "flags": {},
            "order": len(self.nodes),
            "mode": 0,
            "inputs": [],
            "outputs": [],
            "properties": {},
            "widgets_values": widgets or []
        }
        self.nodes.append(node)
        self.next_node_id += 1
        return self

    def build(self) -> dict:
        """Build final workflow JSON."""
        return {
            "nodes": self.nodes,
            "links": self.links,
            "groups": [],
            "config": {},
            "extra": {},
            "version": 0.4
        }


def make_minimal_workflow(checkpoint_file: str, custom_node_type: str | None = None) -> dict:
    """Quick helper for simple test workflows."""
    builder = WorkflowBuilder().add_checkpoint_loader(checkpoint_file)

    if custom_node_type:
        builder.add_custom_node(custom_node_type)

    return builder.build()
