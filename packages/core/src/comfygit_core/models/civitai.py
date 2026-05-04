"""CivitAI API data models and enums."""

from dataclasses import dataclass
from enum import Enum


class ModelType(str, Enum):
    """CivitAI model types."""
    CHECKPOINT = "Checkpoint"
    TEXTUAL_INVERSION = "TextualInversion"
    HYPERNETWORK = "Hypernetwork"
    AESTHETIC_GRADIENT = "AestheticGradient"
    LORA = "LORA"
    CONTROLNET = "Controlnet"
    POSES = "Poses"


class SortOrder(str, Enum):
    """Sort order for model search."""
    HIGHEST_RATED = "Highest Rated"
    MOST_DOWNLOADED = "Most Downloaded"
    NEWEST = "Newest"


class TimePeriod(str, Enum):
    """Time period for sorting."""
    ALL_TIME = "AllTime"
    YEAR = "Year"
    MONTH = "Month"
    WEEK = "Week"
    DAY = "Day"


class CommercialUse(str, Enum):
    """Commercial use permissions."""
    NONE = "None"
    IMAGE = "Image"
    RENT = "Rent"
    SELL = "Sell"


class FileFormat(str, Enum):
    """Model file format."""
    SAFETENSOR = "SafeTensor"
    PICKLE_TENSOR = "PickleTensor"
    OTHER = "Other"


class FloatPrecision(str, Enum):
    """Float precision."""
    FP16 = "fp16"
    FP32 = "fp32"


class ModelSize(str, Enum):
    """Model size."""
    FULL = "full"
    PRUNED = "pruned"


def _safe_enum(enum_cls, value):
    """Parse provider enum values without failing on newly added API values."""
    if value is None:
        return None
    try:
        return enum_cls(value)
    except ValueError:
        return value


@dataclass
class FileHashes:
    """File hash values for different algorithms."""
    auto_v1: str | None = None
    auto_v2: str | None = None
    sha256: str | None = None
    crc32: str | None = None
    blake3: str | None = None

    @classmethod
    def from_api_data(cls, data: dict | None) -> "FileHashes | None":
        """Parse from API response."""
        if not data:
            return None
        return cls(
            auto_v1=data.get("AutoV1"),
            auto_v2=data.get("AutoV2"),
            sha256=data.get("SHA256"),
            crc32=data.get("CRC32"),
            blake3=data.get("BLAKE3"),
        )


@dataclass
class CivitAIFile:
    """Model file information."""
    id: int
    name: str
    size_kb: float
    type: str = "Model"
    pickle_scan_result: str | None = None
    pickle_scan_message: str | None = None
    virus_scan_result: str | None = None
    scanned_at: str | None = None
    primary: bool = False
    download_url: str | None = None
    hashes: FileHashes | None = None

    # Metadata fields
    fp: FloatPrecision | None = None
    size: ModelSize | None = None
    format: FileFormat | None = None

    @classmethod
    def from_api_data(cls, data: dict) -> "CivitAIFile":
        """Parse from API response."""
        metadata = data.get("metadata", {})
        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            size_kb=data.get("sizeKB", 0.0),
            type=data.get("type", "Model"),
            pickle_scan_result=data.get("pickleScanResult"),
            pickle_scan_message=data.get("pickleScanMessage"),
            virus_scan_result=data.get("virusScanResult"),
            scanned_at=data.get("scannedAt"),
            primary=data.get("primary", False),
            download_url=data.get("downloadUrl"),
            hashes=FileHashes.from_api_data(data.get("hashes")),
            fp=_safe_enum(FloatPrecision, metadata.get("fp")),
            size=_safe_enum(ModelSize, metadata.get("size")),
            format=_safe_enum(FileFormat, metadata.get("format")),
        )

    def get_preferred_hash(self) -> str | None:
        """Get the best available hash for identification (prefers SHA256)."""
        if not self.hashes:
            return None
        return (self.hashes.sha256 or self.hashes.blake3 or
                self.hashes.auto_v2 or self.hashes.auto_v1 or
                self.hashes.crc32)


@dataclass
class CivitAIImage:
    """Model preview image."""
    id: str
    url: str
    nsfw: bool
    width: int
    height: int
    hash: str
    meta: dict | None = None

    @classmethod
    def from_api_data(cls, data: dict) -> "CivitAIImage":
        """Parse from API response."""
        return cls(
            id=str(data.get("id", "")),
            url=data.get("url", ""),
            nsfw=bool(data.get("nsfw", False)),
            width=data.get("width", 0),
            height=data.get("height", 0),
            hash=data.get("hash", ""),
            meta=data.get("meta"),
        )


@dataclass
class CivitAIBasicModelInfo:
    """Basic model information (nested in version response)."""
    name: str
    type: str | None = None
    nsfw: bool = False
    poi: bool = False

    @classmethod
    def from_api_data(cls, data: dict | None) -> "CivitAIBasicModelInfo | None":
        """Parse from API response."""
        if not data:
            return None
        return cls(
            name=data.get("name", ""),
            type=data.get("type"),
            nsfw=data.get("nsfw", False),
            poi=data.get("poi", False),
        )


@dataclass
class CivitAIModelVersion:
    """Model version information."""
    id: int
    model_id: int
    name: str
    description: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    base_model: str | None = None
    early_access_time_frame: int = 0
    download_url: str | None = None
    trained_words: list[str] | None = None
    files: list[CivitAIFile] | None = None
    images: list[CivitAIImage] | None = None
    model: CivitAIBasicModelInfo | None = None
    download_count: int = 0
    rating_count: int = 0
    rating: float = 0.0

    @classmethod
    def from_api_data(cls, data: dict) -> "CivitAIModelVersion":
        """Parse from API response."""
        stats = data.get("stats", {})
        return cls(
            id=data.get("id", 0),
            model_id=data.get("modelId", 0),
            name=data.get("name", ""),
            description=data.get("description"),
            created_at=data.get("createdAt"),
            updated_at=data.get("updatedAt"),
            base_model=data.get("baseModel"),
            early_access_time_frame=data.get("earlyAccessTimeFrame", 0),
            download_url=data.get("downloadUrl"),
            trained_words=data.get("trainedWords", []),
            files=[CivitAIFile.from_api_data(f) for f in data.get("files", [])],
            images=[CivitAIImage.from_api_data(i) for i in data.get("images", [])],
            model=CivitAIBasicModelInfo.from_api_data(data.get("model")),
            download_count=stats.get("downloadCount", 0),
            rating_count=stats.get("ratingCount", 0),
            rating=stats.get("rating", 0.0),
        )


@dataclass
class CivitAICreator:
    """Model creator information."""
    username: str
    image: str | None = None

    @classmethod
    def from_api_data(cls, data: dict) -> "CivitAICreator":
        """Parse from API response."""
        return cls(
            username=data.get("username", ""),
            image=data.get("image"),
        )


@dataclass
class CivitAIModel:
    """CivitAI model information."""
    id: int
    name: str
    description: str | None = None
    type: ModelType | None = None
    nsfw: bool = False
    tags: list[str] | None = None
    mode: str | None = None  # "Archived" or "TakenDown"
    creator: CivitAICreator | None = None
    model_versions: list[CivitAIModelVersion] | None = None

    # Stats
    download_count: int = 0
    favorite_count: int = 0
    comment_count: int = 0
    rating_count: int = 0
    rating: float = 0.0

    @classmethod
    def from_api_data(cls, data: dict) -> "CivitAIModel":
        """Parse from API response."""
        stats = data.get("stats", {})
        creator_data = data.get("creator")

        # Handle tags that can be either strings or objects with 'name' field
        tags_raw = data.get("tags", [])
        tags = []
        for tag in tags_raw:
            if isinstance(tag, str):
                tags.append(tag)
            elif isinstance(tag, dict) and "name" in tag:
                tags.append(tag["name"])

        return cls(
            id=data.get("id", 0),
            name=data.get("name", ""),
            description=data.get("description"),
            type=_safe_enum(ModelType, data.get("type")),
            nsfw=data.get("nsfw", False),
            tags=tags,
            mode=data.get("mode"),
            creator=CivitAICreator.from_api_data(creator_data) if creator_data else None,
            model_versions=[
                CivitAIModelVersion.from_api_data(v)
                for v in data.get("modelVersions", [])
            ],
            download_count=stats.get("downloadCount", 0),
            favorite_count=stats.get("favoriteCount", 0),
            comment_count=stats.get("commentCount", 0),
            rating_count=stats.get("ratingCount", 0),
            rating=stats.get("rating", 0.0),
        )

    def get_latest_version(self) -> CivitAIModelVersion | None:
        """Get the most recent model version."""
        if not self.model_versions:
            return None
        return self.model_versions[0]  # API returns newest first

    def get_primary_file(self) -> CivitAIFile | None:
        """Get the primary file from the latest version."""
        latest = self.get_latest_version()
        if not latest or not latest.files:
            return None

        # Find primary file or default to first
        for file in latest.files:
            if file.primary:
                return file
        return latest.files[0]

    def find_file_by_hash(self, hash_value: str) -> CivitAIFile | None:
        """Find a file across all versions by any of its hashes."""
        if not self.model_versions:
            return None

        hash_upper = hash_value.upper()
        for version in self.model_versions:
            if not version.files:
                continue
            for file in version.files:
                if not file.hashes:
                    continue
                if (file.hashes.auto_v1 == hash_upper or
                    file.hashes.auto_v2 == hash_upper or
                    file.hashes.sha256 == hash_upper or
                    file.hashes.crc32 == hash_upper or
                    file.hashes.blake3 == hash_upper):
                    return file
        return None


@dataclass
class SearchParams:
    """Parameters for model search."""
    query: str | None = None
    tag: str | None = None
    username: str | None = None
    types: list[ModelType] | None = None
    sort: SortOrder | None = None
    period: TimePeriod | None = None
    limit: int = 20
    page: int = 1
    nsfw: bool | None = None
    commercial_use: CommercialUse | None = None
    allow_no_credit: bool | None = None
    allow_derivatives: bool | None = None
    allow_different_licenses: bool | None = None
    primary_file_only: bool | None = None
    supports_generation: bool | None = None

    def to_dict(self) -> dict:
        """Convert to query parameters dict."""
        params = {}

        if self.query:
            params["query"] = self.query
        if self.tag:
            params["tag"] = self.tag
        if self.username:
            params["username"] = self.username
        if self.types:
            # CivitAI expects multiple types as comma-separated string
            params["types"] = ",".join([t.value for t in self.types])
        if self.sort:
            params["sort"] = self.sort.value
        if self.period:
            params["period"] = self.period.value
        if self.limit:
            params["limit"] = self.limit
        # Only include page if not using query (CivitAI restriction)
        if self.page and self.page > 1 and not self.query:
            params["page"] = self.page
        if self.nsfw is not None:
            params["nsfw"] = str(self.nsfw).lower()
        if self.commercial_use:
            params["allowCommercialUse"] = self.commercial_use.value
        if self.allow_no_credit is not None:
            params["allowNoCredit"] = str(self.allow_no_credit).lower()
        if self.allow_derivatives is not None:
            params["allowDerivatives"] = str(self.allow_derivatives).lower()
        if self.allow_different_licenses is not None:
            params["allowDifferentLicenses"] = str(self.allow_different_licenses).lower()
        if self.primary_file_only is not None:
            params["primaryFileOnly"] = str(self.primary_file_only).lower()
        if self.supports_generation is not None:
            params["supportsGeneration"] = str(self.supports_generation).lower()

        return params


@dataclass
class CivitAITag:
    """Tag information."""
    name: str
    model_count: int
    link: str

    @classmethod
    def from_api_data(cls, data: dict) -> "CivitAITag":
        """Parse from API response."""
        return cls(
            name=data.get("name", ""),
            model_count=data.get("modelCount", 0),
            link=data.get("link", ""),
        )


@dataclass
class SearchResponse:
    """Model search response with pagination."""
    items: list[CivitAIModel]
    total_items: int
    current_page: int
    page_size: int
    total_pages: int
    next_page: str | None = None
    prev_page: str | None = None

    @classmethod
    def from_api_data(cls, data: dict) -> "SearchResponse":
        """Parse from API response."""
        metadata = data.get("metadata", {})
        return cls(
            items=[CivitAIModel.from_api_data(m) for m in data.get("items", [])],
            total_items=int(metadata.get("totalItems", 0)),
            current_page=int(metadata.get("currentPage", 1)),
            page_size=int(metadata.get("pageSize", 20)),
            total_pages=int(metadata.get("totalPages", 1)),
            next_page=metadata.get("nextPage"),
            prev_page=metadata.get("prevPage"),
        )
