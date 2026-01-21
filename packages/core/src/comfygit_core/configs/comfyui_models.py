"""Default ComfyUI models configuration"""

# Multi-model widget configurations: node_type -> list of widget indices containing models
# These nodes load multiple models from different widget positions
MULTI_MODEL_WIDGET_CONFIGS: dict[str, list[int]] = {
    "CheckpointLoader": [0, 1],           # checkpoint, config
    "DualCLIPLoader": [0, 1],             # clip_name1, clip_name2
    "TripleCLIPLoader": [0, 1, 2],        # clip_name1, clip_name2, clip_name3
    "QuadrupleCLIPLoader": [0, 1, 2, 3],  # clip_name1, clip_name2, clip_name3, clip_name4
}

COMFYUI_MODELS_CONFIG = {
    "version": "2024.1",
    "default_extensions": [
        ".ckpt",
        ".pt",
        ".pth",
        ".pt2",
        ".bin",
        ".safetensors",
        ".pkl",
        ".sft",
    ],
    "standard_directories": [
        "audio_encoders",
        "checkpoints",
        "clip",
        "clip_vision",
        "configs",
        "controlnet",
        "t2i_adapter",
        "diffusers",
        "diffusion_models",
        "embeddings",
        "gligen",
        "hypernetworks",
        "loras",
        "model_patches",
        "photomaker",
        "style_models",
        "text_encoders",
        "unet",
        "upscale_models",
        "vae",
        "vae_approx",
    ],
    "directory_overrides": {"configs": {"extensions": [".yaml", ".yml", ".json"]}},
    "node_directory_mappings": {
        "CheckpointLoaderSimple": ["checkpoints"],
        "CheckpointLoader": ["checkpoints", "configs"],
        "unCLIPCheckpointLoader": ["checkpoints"],
        "ImageOnlyCheckpointLoader": ["checkpoints"],
        "VAELoader": ["vae", "vae_approx"],
        "LoraLoader": ["loras"],
        "LoraLoaderModelOnly": ["loras"],
        "CLIPLoader": ["clip"],
        "DualCLIPLoader": ["clip"],
        "TripleCLIPLoader": ["clip"],
        "QuadrupleCLIPLoader": ["clip"],
        "UNETLoader": ["diffusion_models"],
        "CLIPVisionLoader": ["clip_vision"],
        "ControlNetLoader": ["controlnet"],
        "DiffControlNetLoader": ["controlnet"],
        "StyleModelLoader": ["style_models"],
        "UpscaleModelLoader": ["upscale_models"],
        "GLIGENLoader": ["gligen"],
        "HypernetworkLoader": ["hypernetworks"],
        "PhotoMakerLoader": ["photomaker"],
        "DiffusersLoader": ["diffusers"],
    },
    "node_widget_indices": {"CheckpointLoader": 1},
}
