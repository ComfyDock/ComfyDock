from dataclasses import dataclass, field


@dataclass
class RegistryNodeVersion:
    """Version information for a node."""
    changelog: str
    dependencies: list[str]
    deprecated: bool
    id: str
    version: str
    download_url: str

    @classmethod
    def from_api_data(cls, api_data: dict) -> "RegistryNodeVersion | None":
        if not api_data:
            return None
        return cls(
            changelog=api_data.get("changelog", ""),
            dependencies=api_data.get("dependencies", []),
            deprecated=api_data.get("deprecated", False),
            id=api_data.get("id", ""),
            version=api_data.get("version", ""),
            download_url=api_data.get("downloadUrl", ""),
        )

@dataclass
class RegistryNodeInfo:
    """Information about a custom node."""
    id: str
    name: str
    description: str
    author: str | None = None
    license: str | None = None
    icon: str | None = None
    repository: str | None = None
    tags: list[str] = field(default_factory=list)
    latest_version: RegistryNodeVersion | None = None

    @classmethod
    def from_api_data(cls, api_data: dict) -> "RegistryNodeInfo | None":
        # Ensure dict has id, name and description keys:
        id = api_data.get("id")
        name = api_data.get("name")
        description = api_data.get("description")
        if not id or not name or not description:
            return None
        return cls(
            id=id,
            name=name,
            description=description,
            author=api_data.get("author"),
            license=api_data.get("license"),
            icon=api_data.get("icon"),
            repository=api_data.get("repository"),
            tags=api_data.get("tags", []),
            latest_version=RegistryNodeVersion.from_api_data(api_data.get("latest_version", {})),
        )
