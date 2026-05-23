from dataclasses import dataclass


@dataclass(repr=False)
class APICredentials:
    """Secure storage for external API credentials."""
    civitai_token: str | None = None
    huggingface_token: str | None = None
    github_token: str | None = None

    @classmethod
    def from_dict(cls, data):
        if not data:
            return None
        return cls(
            civitai_token=data.get("civitai_token"),
            huggingface_token=data.get("huggingface_token"),
            github_token=data.get("github_token"),
        )

    def to_dict(self):
        result = {}
        if self.civitai_token:
            result["civitai_token"] = self.civitai_token
        if self.huggingface_token:
            result["huggingface_token"] = self.huggingface_token
        if self.github_token:
            result["github_token"] = self.github_token
        return result

    def __repr__(self):
        """Obfuscate tokens in logs."""
        parts = []
        if self.civitai_token:
            parts.append(f"civitai_token='***{self.civitai_token[-4:]}'")
        if self.huggingface_token:
            parts.append(f"huggingface_token='***{self.huggingface_token[-4:]}'")
        if self.github_token:
            parts.append(f"github_token='***{self.github_token[-4:]}'")
        return f"APICredentials({', '.join(parts) if parts else ''})"

@dataclass
class ModelDirectory:
    path: str
    added_at: str
    last_sync: str

    @classmethod
    def from_dict(cls, data):
        return cls(
            path=data["path"],
            added_at=data["added_at"],
            last_sync=data["last_sync"],
        )

    @classmethod
    def to_dict(cls, instance):
        return instance.__dict__

@dataclass
class WorkspaceConfig:
    version: int
    active_environment: str
    created_at: str
    global_model_directory: ModelDirectory | None
    api_credentials: APICredentials | None = None
    external_uv_cache: str | None = None  # Optional external UV cache path for dev/testing

    @classmethod
    def from_dict(cls, data):
        # Note: prefer_registry_cache is intentionally ignored (removed in 0.3.11)
        return cls(
            version=data["version"],
            active_environment=data["active_environment"],
            created_at=data["created_at"],
            global_model_directory=ModelDirectory.from_dict(data["global_model_directory"]) if data.get("global_model_directory") else None,
            api_credentials=APICredentials.from_dict(data.get("api_credentials")) if data.get("api_credentials") else None,
            external_uv_cache=data.get("external_uv_cache"),
        )

    @classmethod
    def to_dict(cls, instance):
        result = {
            "version": instance.version,
            "active_environment": instance.active_environment,
            "created_at": instance.created_at,
            "global_model_directory": ModelDirectory.to_dict(instance.global_model_directory) if instance.global_model_directory else None,
            "api_credentials": instance.api_credentials.to_dict() if instance.api_credentials else None,
            "external_uv_cache": instance.external_uv_cache,
        }
        return result
