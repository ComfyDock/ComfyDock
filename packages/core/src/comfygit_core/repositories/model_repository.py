"""ModelIndexManager - Model-specific database operations and schema management."""

import json
from datetime import datetime
from pathlib import Path

import xxhash
from blake3 import blake3

from ..infrastructure.sqlite_manager import SQLiteManager
from ..logging.logging_config import get_logger
from ..models.exceptions import ComfyDockError
from ..models.shared import ModelWithLocation

logger = get_logger(__name__)

# Database schema version
# v10: Switch from blake3 to xxhash for short hash (7x faster)
SCHEMA_VERSION = 10

# Models table: One entry per unique model file (by hash)
CREATE_MODELS_TABLE = """
CREATE TABLE IF NOT EXISTS models (
    hash TEXT PRIMARY KEY,
    file_size INTEGER NOT NULL,
    blake3_hash TEXT,
    sha256_hash TEXT,
    first_seen INTEGER NOT NULL,
    metadata TEXT DEFAULT '{}'
)
"""

# Model locations: All instances of each model across all directories
CREATE_MODEL_LOCATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS model_locations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_hash TEXT NOT NULL,
    base_directory TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    filename TEXT NOT NULL,
    mtime REAL NOT NULL,
    last_seen INTEGER NOT NULL,
    FOREIGN KEY (model_hash) REFERENCES models(hash) ON DELETE CASCADE,
    UNIQUE(base_directory, relative_path)
)
"""

# Model sources: Track where models can be downloaded from
CREATE_MODEL_SOURCES_TABLE = """
CREATE TABLE IF NOT EXISTS model_sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    model_hash TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_url TEXT NOT NULL,
    metadata TEXT DEFAULT '{}',
    added_time INTEGER NOT NULL,
    FOREIGN KEY (model_hash) REFERENCES models(hash) ON DELETE CASCADE,
    UNIQUE(model_hash, source_url)
)
"""

CREATE_SCHEMA_INFO_TABLE = """
CREATE TABLE IF NOT EXISTS schema_info (
    version INTEGER PRIMARY KEY
)
"""

# Indexes for efficient queries
CREATE_LOCATIONS_HASH_INDEX = """
CREATE INDEX IF NOT EXISTS idx_locations_hash ON model_locations(model_hash)
"""

CREATE_LOCATIONS_PATH_INDEX = """
CREATE INDEX IF NOT EXISTS idx_locations_path ON model_locations(relative_path)
"""

CREATE_MODELS_BLAKE3_INDEX = """
CREATE INDEX IF NOT EXISTS idx_models_blake3 ON models(blake3_hash)
"""

CREATE_MODELS_SHA256_INDEX = """
CREATE INDEX IF NOT EXISTS idx_models_sha256 ON models(sha256_hash)
"""

CREATE_LOCATIONS_FILENAME_INDEX = """
CREATE INDEX IF NOT EXISTS idx_locations_filename ON model_locations(filename)
"""

CREATE_SOURCES_HASH_INDEX = """
CREATE INDEX IF NOT EXISTS idx_sources_hash ON model_sources(model_hash)
"""

CREATE_SOURCES_TYPE_INDEX = """
CREATE INDEX IF NOT EXISTS idx_sources_type ON model_sources(source_type)
"""


class ModelRepository:
    """Model-specific database operations and schema management."""

    def __init__(self, db_path: Path, current_directory: Path | None = None):
        """Initialize ModelIndexManager.

        Args:
            db_path: Path to SQLite database file
            current_directory: Current models directory for filtering queries
        """
        self.db_path = db_path
        self.sqlite = SQLiteManager(db_path)
        self.current_directory = current_directory
        self.ensure_schema()

    def set_current_directory(self, directory: Path) -> None:
        """Set the current models directory for query filtering."""
        self.current_directory = directory

    def ensure_schema(self) -> None:
        """Create database schema if needed."""
        self.sqlite.create_table(CREATE_MODELS_TABLE)
        self.sqlite.create_table(CREATE_MODEL_LOCATIONS_TABLE)
        self.sqlite.create_table(CREATE_MODEL_SOURCES_TABLE)
        self.sqlite.create_table(CREATE_SCHEMA_INFO_TABLE)
        self.sqlite.execute_query(CREATE_LOCATIONS_HASH_INDEX)
        self.sqlite.execute_query(CREATE_LOCATIONS_PATH_INDEX)
        self.sqlite.execute_query(CREATE_LOCATIONS_FILENAME_INDEX)
        self.sqlite.execute_query(CREATE_SOURCES_HASH_INDEX)
        self.sqlite.execute_query(CREATE_SOURCES_TYPE_INDEX)
        self.sqlite.execute_query(CREATE_MODELS_BLAKE3_INDEX)
        self.sqlite.execute_query(CREATE_MODELS_SHA256_INDEX)

        # Check schema version
        current_version = self.get_schema_version()
        if current_version != SCHEMA_VERSION:
            self.migrate_schema(current_version, SCHEMA_VERSION)

    def get_schema_version(self) -> int:
        """Get current schema version from database.

        Returns:
            Schema version number, 0 if not set
        """
        try:
            results = self.sqlite.execute_query("SELECT version FROM schema_info LIMIT 1")
            if results:
                return results[0]['version']
            else:
                # First time setup - insert current version
                self.sqlite.execute_write(
                    "INSERT INTO schema_info (version) VALUES (?)",
                    (SCHEMA_VERSION,)
                )
                return SCHEMA_VERSION
        except ComfyDockError:
            return 0

    def migrate_schema(self, from_version: int, to_version: int) -> None:
        """Migrate database schema between versions.

        Args:
            from_version: Current schema version
            to_version: Target schema version
        """
        if from_version == to_version:
            return

        logger.info(f"Dropping old schema v{from_version} and creating new v{to_version}")

        # Drop everything and recreate
        self.sqlite.execute_write("DROP TABLE IF EXISTS model_sources")
        self.sqlite.execute_write("DROP TABLE IF EXISTS model_locations")
        self.sqlite.execute_write("DROP TABLE IF EXISTS models")
        self.sqlite.execute_write("DROP TABLE IF EXISTS schema_info")

        # Recreate with new schema
        self.sqlite.create_table(CREATE_MODELS_TABLE)
        self.sqlite.create_table(CREATE_MODEL_LOCATIONS_TABLE)
        self.sqlite.create_table(CREATE_MODEL_SOURCES_TABLE)
        self.sqlite.create_table(CREATE_SCHEMA_INFO_TABLE)
        self.sqlite.execute_query(CREATE_LOCATIONS_HASH_INDEX)
        self.sqlite.execute_query(CREATE_LOCATIONS_PATH_INDEX)
        self.sqlite.execute_query(CREATE_LOCATIONS_FILENAME_INDEX)
        self.sqlite.execute_query(CREATE_SOURCES_HASH_INDEX)
        self.sqlite.execute_query(CREATE_SOURCES_TYPE_INDEX)
        self.sqlite.execute_query(CREATE_MODELS_BLAKE3_INDEX)
        self.sqlite.execute_query(CREATE_MODELS_SHA256_INDEX)

        # Set version
        self.sqlite.execute_write(
            "INSERT INTO schema_info (version) VALUES (?)",
            (to_version,)
        )

    def ensure_model(self, hash: str, file_size: int, blake3_hash: str | None = None,
                    sha256_hash: str | None = None) -> None:
        """Ensure model exists in models table.

        Args:
            hash: Model hash (short hash or blake3 if collision)
            file_size: File size in bytes
            blake3_hash: Full blake3 hash if available
            sha256_hash: SHA256 hash if available
        """
        query = """
        INSERT OR IGNORE INTO models
        (hash, file_size, blake3_hash, sha256_hash, first_seen, metadata)
        VALUES (?, ?, ?, ?, ?, '{}')
        """

        self.sqlite.execute_write(
            query,
            (hash, file_size, blake3_hash, sha256_hash, int(datetime.now().timestamp()))
        )

        logger.debug(f"Ensured model in index: {hash[:8]}...")

    def add_location(self, model_hash: str, base_directory: Path, relative_path: str,
                    filename: str, mtime: float) -> None:
        """Add or update a file location for a model.

        Args:
            model_hash: Hash of the model this location belongs to
            base_directory: Base directory path (e.g., /path/to/models)
            relative_path: Path relative to base directory
            filename: Just the filename part
            mtime: File modification time
        """
        query = """
        INSERT OR REPLACE INTO model_locations
        (model_hash, base_directory, relative_path, filename, mtime, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
        """

        base_dir_str = str(base_directory.resolve())
        # Normalize to forward slashes for cross-platform consistency
        normalized_path = relative_path.replace('\\', '/')
        self.sqlite.execute_write(
            query,
            (model_hash, base_dir_str, normalized_path, filename, mtime, int(datetime.now().timestamp()))
        )

        logger.debug(f"Added location: {base_dir_str}/{relative_path} for model {model_hash[:8]}...")

    def get_model(self, hash: str) -> ModelWithLocation | None:
        """Get model by hash.

        Args:
            hash: Model hash to look up

        Returns:
            ModelWithLocation or None if not found
        """
        result = self.find_model_by_hash(hash)
        return result[0] if result else None

    def has_model(self, hash: str) -> bool:
        """Check if model exists by hash.

        Args:
            hash: Model hash to check

        Returns:
            True if model exists, False otherwise
        """
        query = "SELECT 1 FROM models WHERE hash = ? LIMIT 1"
        results = self.sqlite.execute_query(query, (hash,))
        return len(results) > 0

    def get_locations(self, model_hash: str) -> list[dict]:
        """Get all locations for a model.

        Args:
            model_hash: Hash of model to get locations for

        Returns:
            List of location dictionaries
        """
        query = "SELECT * FROM model_locations WHERE model_hash = ? ORDER BY relative_path"
        return self.sqlite.execute_query(query, (model_hash,))

    def get_all_locations(self, base_directory: Path | None = None) -> list[dict]:
        """Get model locations, optionally filtered by base directory.

        Args:
            base_directory: If provided, only return locations from this directory

        Returns:
            List of location dictionaries
        """
        if base_directory:
            base_dir_str = str(base_directory.resolve())
            query = "SELECT * FROM model_locations WHERE base_directory = ? ORDER BY relative_path"
            return self.sqlite.execute_query(query, (base_dir_str,))
        else:
            query = "SELECT * FROM model_locations ORDER BY relative_path"
            return self.sqlite.execute_query(query)

    def remove_location(self, relative_path: str) -> bool:
        """Remove a specific location.

        Args:
            relative_path: Path to remove

        Returns:
            True if location was removed, False if not found
        """
        query = "DELETE FROM model_locations WHERE relative_path = ?"
        rows_affected = self.sqlite.execute_write(query, (relative_path,))
        return rows_affected > 0

    def remove_location_by_id(self, location_id: int) -> bool:
        """Remove a specific model location by database id.

        Args:
            location_id: model_locations.id value to remove

        Returns:
            True if location was removed, False if not found
        """
        query = "DELETE FROM model_locations WHERE id = ?"
        rows_affected = self.sqlite.execute_write(query, (location_id,))
        return rows_affected > 0

    def remove_location_for_directory(self, base_directory: Path, relative_path: str) -> bool:
        """Remove a model location scoped to one base directory.

        Args:
            base_directory: Base models directory for the location
            relative_path: Path relative to that base directory

        Returns:
            True if location was removed, False if not found
        """
        query = """
        DELETE FROM model_locations
        WHERE base_directory = ? AND relative_path = ?
        """
        rows_affected = self.sqlite.execute_write(
            query,
            (str(base_directory.resolve()), relative_path.replace('\\', '/')),
        )
        return rows_affected > 0

    def clean_stale_locations(self, models_dir: Path) -> int:
        """Remove locations from this directory that no longer exist on disk.

        Only checks locations belonging to the specified directory.
        Preserves locations from other directories.

        Args:
            models_dir: Base models directory path

        Returns:
            Number of stale locations removed
        """
        base_dir_str = str(models_dir.resolve())
        query = "SELECT id, relative_path FROM model_locations WHERE base_directory = ?"
        results = self.sqlite.execute_query(query, (base_dir_str,))

        removed_count = 0
        for row in results:
            file_path = models_dir / row['relative_path']
            if not file_path.exists():
                delete_query = "DELETE FROM model_locations WHERE id = ?"
                self.sqlite.execute_write(delete_query, (row['id'],))
                removed_count += 1

        if removed_count > 0:
            logger.info(f"Cleaned up {removed_count} stale model locations from {base_dir_str}")

        return removed_count

    def get_all_models(self, base_directory: Path | None = "USE_CURRENT") -> list[ModelWithLocation]:
        """Get all models with their locations, optionally filtered by directory.

        Args:
            base_directory: Directory to filter by. Defaults to current_directory.
                          Pass None explicitly to get models from all directories.

        Returns:
            List of ModelWithLocation objects
        """
        if base_directory == "USE_CURRENT":
            base_directory = self.current_directory

        if base_directory:
            base_dir_str = str(base_directory.resolve())
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.base_directory = ?
            ORDER BY l.relative_path
            """
            results = self.sqlite.execute_query(query, (base_dir_str,))
        else:
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            ORDER BY l.relative_path
            """
            results = self.sqlite.execute_query(query)
        models = []

        for row in results:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            model = ModelWithLocation(
                hash=row['hash'],
                file_size=row['file_size'],
                blake3_hash=row['blake3_hash'],
                sha256_hash=row['sha256_hash'],
                relative_path=row['relative_path'],
                filename=row['filename'],
                mtime=row['mtime'],
                last_seen=row['last_seen'],
                base_directory=row.get('base_directory'),
                metadata=metadata
            )
            models.append(model)

        return models

    def find_model_by_hash(self, hash_query: str, base_directory: Path | None = "USE_CURRENT") -> list[ModelWithLocation]:
        """Find models by hash prefix, optionally filtered by directory.

        Args:
            hash_query: Hash or hash prefix to search for
            base_directory: Directory to filter by. Defaults to current_directory.
                          Pass None explicitly to search all directories.

        Returns:
            List of matching ModelWithLocation objects
        """
        if base_directory == "USE_CURRENT":
            base_directory = self.current_directory

        # Support both exact match and prefix matching
        if base_directory:
            base_dir_str = str(base_directory.resolve())
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE (m.hash LIKE ? OR m.blake3_hash LIKE ? OR m.sha256_hash LIKE ?)
              AND l.base_directory = ?
            ORDER BY l.relative_path
            """
            search_pattern = f"{hash_query}%"
            results = self.sqlite.execute_query(query, (search_pattern, search_pattern, search_pattern, base_dir_str))
        else:
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE m.hash LIKE ? OR m.blake3_hash LIKE ? OR m.sha256_hash LIKE ?
            ORDER BY l.relative_path
            """
            search_pattern = f"{hash_query}%"
            results = self.sqlite.execute_query(query, (search_pattern, search_pattern, search_pattern))

        models = []
        for row in results:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            model = ModelWithLocation(
                hash=row['hash'],
                file_size=row['file_size'],
                blake3_hash=row['blake3_hash'],
                sha256_hash=row['sha256_hash'],
                relative_path=row['relative_path'],
                filename=row['filename'],
                mtime=row['mtime'],
                last_seen=row['last_seen'],
                base_directory=row.get('base_directory'),
                metadata=metadata
            )
            models.append(model)

        return models

    def find_by_filename(self, filename_query: str, base_directory: Path | None = "USE_CURRENT") -> list[ModelWithLocation]:
        """Find models by exact filename match.

        Args:
            filename_query: Exact filename to search for
            base_directory: Directory to filter by. Defaults to current_directory.

        Returns:
            List of matching ModelWithLocation objects
        """
        if base_directory == "USE_CURRENT":
            base_directory = self.current_directory

        if base_directory:
            base_dir_str = str(base_directory.resolve())
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.filename = ? AND l.base_directory = ?
            ORDER BY l.relative_path
            """
            results = self.sqlite.execute_query(query, (filename_query, base_dir_str))
        else:
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.filename = ?
            ORDER BY l.relative_path
            """
            results = self.sqlite.execute_query(query, (filename_query,))

        models = []
        for row in results:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            model = ModelWithLocation(
                hash=row['hash'],
                file_size=row['file_size'],
                blake3_hash=row['blake3_hash'],
                sha256_hash=row['sha256_hash'],
                relative_path=row['relative_path'],
                filename=row['filename'],
                mtime=row['mtime'],
                last_seen=row['last_seen'],
                base_directory=row.get('base_directory'),
                metadata=metadata
            )
            models.append(model)

        return models

    def get_sources(self, model_hash: str) -> list[dict]:
        """Get all download sources for a model.

        Args:
            model_hash: Hash of model to get sources for

        Returns:
            List of source dictionaries with type, url, and metadata
        """
        query = """
        SELECT source_type, source_url, metadata, added_time
        FROM model_sources
        WHERE model_hash = ?
        ORDER BY added_time DESC
        """

        results = self.sqlite.execute_query(query, (model_hash,))
        sources = []

        for row in results:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            source = {
                'type': row['source_type'],
                'url': row['source_url'],
                'metadata': metadata,
                'added_time': row['added_time']
            }
            sources.append(source)

        return sources

    def add_source(self, model_hash: str, source_type: str, source_url: str, metadata: dict | None = None) -> None:
        """Add a download source for a model.

        Args:
            model_hash: Hash of the model
            source_type: Type of source (civitai, huggingface, custom, etc.)
            source_url: URL where model can be downloaded
            metadata: Optional metadata about the source
        """
        if metadata is None:
            metadata = {}

        query = """
        INSERT OR REPLACE INTO model_sources
        (model_hash, source_type, source_url, metadata, added_time)
        VALUES (?, ?, ?, ?, ?)
        """

        self.sqlite.execute_write(
            query,
            (model_hash, source_type, source_url, json.dumps(metadata), int(datetime.now().timestamp()))
        )

        logger.debug(f"Added source for {model_hash[:8]}...: {source_type} - {source_url}")

    def remove_source(self, model_hash: str, source_url: str) -> bool:
        """Remove a download source for a model.

        Args:
            model_hash: Hash of the model
            source_url: URL of the source to remove

        Returns:
            True if source was removed, False if source didn't exist
        """
        query = """
        DELETE FROM model_sources
        WHERE model_hash = ? AND source_url = ?
        """

        rows_affected = self.sqlite.execute_write(query, (model_hash, source_url))

        if rows_affected > 0:
            logger.debug(f"Removed source for {model_hash[:8]}...: {source_url}")
            return True
        else:
            logger.debug(f"Source not found for {model_hash[:8]}...: {source_url}")
            return False

    def get_stats(self, base_directory: Path | None = "USE_CURRENT") -> dict[str, int]:
        """Get index statistics, optionally filtered by directory.

        Args:
            base_directory: Directory to filter by. Defaults to current_directory.
                          Pass None explicitly to get stats from all directories.

        Returns:
            Dictionary with index statistics
        """
        if base_directory == "USE_CURRENT":
            base_directory = self.current_directory

        if base_directory:
            base_dir_str = str(base_directory.resolve())
            models_query = """
            SELECT COUNT(DISTINCT m.hash) as count
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.base_directory = ?
            """
            locations_query = "SELECT COUNT(*) as count FROM model_locations WHERE base_directory = ?"

            models_result = self.sqlite.execute_query(models_query, (base_dir_str,))
            locations_result = self.sqlite.execute_query(locations_query, (base_dir_str,))
        else:
            models_query = """
            SELECT COUNT(DISTINCT m.hash) as count
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            """
            locations_query = "SELECT COUNT(*) as count FROM model_locations"

            models_result = self.sqlite.execute_query(models_query)
            locations_result = self.sqlite.execute_query(locations_query)

        sources_query = "SELECT COUNT(*) as count FROM model_sources"
        sources_result = self.sqlite.execute_query(sources_query)

        return {
            'total_models': models_result[0]['count'] if models_result else 0,
            'total_locations': locations_result[0]['count'] if locations_result else 0,
            'total_sources': sources_result[0]['count'] if sources_result else 0
        }

    def update_blake3(self, hash: str, blake3_hash: str) -> None:
        """Update full BLAKE3 hash for existing model.

        Args:
            hash: Model hash (primary key)
            blake3_hash: Computed full BLAKE3 hash
        """
        query = "UPDATE models SET blake3_hash = ? WHERE hash = ?"
        rows_affected = self.sqlite.execute_write(query, (blake3_hash, hash))

        if rows_affected == 0:
            raise ComfyDockError(f"Model with hash {hash} not found in index")

        logger.debug(f"Updated BLAKE3 for {hash[:8]}...: {blake3_hash[:8]}...")

    def update_sha256(self, hash: str, sha256_hash: str) -> None:
        """Update SHA256 hash for existing model.

        Args:
            hash: Model hash (primary key)
            sha256_hash: Computed SHA256 hash
        """
        query = "UPDATE models SET sha256_hash = ? WHERE hash = ?"
        rows_affected = self.sqlite.execute_write(query, (sha256_hash, hash))

        if rows_affected == 0:
            raise ComfyDockError(f"Model with hash {hash} not found in index")

        logger.debug(f"Updated SHA256 for {hash[:8]}...: {sha256_hash[:8]}...")

    def calculate_short_hash(self, file_path: Path) -> str:
        """Calculate fast short hash by sampling file chunks using xxhash.

        Samples 5MB each from start, middle, and end of file plus file size.
        Uses xxhash for ~7x faster hashing compared to blake3.

        Args:
            file_path: Path to model file

        Returns:
            16-character hex-encoded hash string (64 bits)

        Raises:
            ComfyDockError: If hash calculation fails
        """
        try:
            if not file_path.exists() or not file_path.is_file():
                raise ComfyDockError(f"File does not exist or is not a regular file: {file_path}")

            file_size = file_path.stat().st_size
            hasher = xxhash.xxh3_128()

            # Include file size as discriminator
            hasher.update(str(file_size).encode())

            chunk_size = 5 * 1024 * 1024  # 5MB chunks

            with open(file_path, 'rb') as f:
                # Start chunk
                hasher.update(f.read(chunk_size))

                # Middle and end chunks for files > 30MB
                if file_size > 30 * 1024 * 1024:
                    # Middle chunk
                    f.seek(file_size // 2 - chunk_size // 2)
                    hasher.update(f.read(chunk_size))

                    # End chunk
                    f.seek(-chunk_size, 2)
                    hasher.update(f.read(chunk_size))

            return hasher.hexdigest()[:16]

        except Exception as e:
            raise ComfyDockError(f"Failed to calculate short hash for {file_path}: {e}")

    def compute_blake3(self, file_path: Path, chunk_size: int = 8192 * 1024) -> str:
        """Calculate full Blake3 hash for model file.

        Only used when short hash collision detected or explicit verification needed.

        Args:
            file_path: Path to model file
            chunk_size: Chunk size for streaming hash calculation

        Returns:
            Hex-encoded hash string

        Raises:
            ComfyDockError: If hash calculation fails
        """
        try:
            hasher = blake3()

            with open(file_path, 'rb') as f:
                while chunk := f.read(chunk_size):
                    hasher.update(chunk)

            return hasher.hexdigest()

        except Exception as e:
            raise ComfyDockError(f"Failed to calculate hash for {file_path}: {e}")

    def compute_sha256(self, file_path: Path) -> str:
        """Compute SHA256 hash for external compatibility.

        Args:
            file_path: Path to file

        Returns:
            SHA256 hash string
        """
        import hashlib

        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            # Read file in chunks to handle large files
            for byte_block in iter(lambda: f.read(8192), b""):
                sha256_hash.update(byte_block)

        return sha256_hash.hexdigest()

    def get_by_category(self, category: str, base_directory: Path | None = "USE_CURRENT") -> list[ModelWithLocation]:
        """Get all models in a specific category, optionally filtered by directory.

        Args:
            category: Category name (e.g., "checkpoints", "loras", "vae")
            base_directory: Directory to filter by. Defaults to current_directory.
                          Pass None explicitly to search all directories.

        Returns:
            List of ModelWithLocation objects in that category
        """
        if base_directory == "USE_CURRENT":
            base_directory = self.current_directory

        if base_directory:
            base_dir_str = str(base_directory.resolve())
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.relative_path LIKE ? AND l.base_directory = ?
            ORDER BY l.filename
            """
            search_pattern = f"{category}/%"
            results = self.sqlite.execute_query(query, (search_pattern, base_dir_str))
        else:
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.relative_path LIKE ?
            ORDER BY l.filename
            """
            search_pattern = f"{category}/%"
            results = self.sqlite.execute_query(query, (search_pattern,))

        models = []
        for row in results:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            model = ModelWithLocation(
                hash=row['hash'],
                file_size=row['file_size'],
                blake3_hash=row['blake3_hash'],
                sha256_hash=row['sha256_hash'],
                relative_path=row['relative_path'],
                filename=row['filename'],
                mtime=row['mtime'],
                last_seen=row['last_seen'],
                base_directory=row.get('base_directory'),
                metadata=metadata
            )
            models.append(model)

        return models

    def find_by_exact_path(self, relative_path: str, base_directory: Path | None = "USE_CURRENT") -> ModelWithLocation | None:
        """Find model by exact relative path, optionally filtered by directory.

        Args:
            relative_path: Exact relative path to match
            base_directory: Directory to filter by. Defaults to current_directory.
                          Pass None explicitly to search all directories.

        Returns:
            ModelWithLocation or None if not found
        """
        if base_directory == "USE_CURRENT":
            base_directory = self.current_directory

        # Normalize to forward slashes for cross-platform consistency
        normalized_path = relative_path.replace('\\', '/')

        if base_directory:
            base_dir_str = str(base_directory.resolve())
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.relative_path = ? AND l.base_directory = ?
            LIMIT 1
            """
            results = self.sqlite.execute_query(query, (normalized_path, base_dir_str))
        else:
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.relative_path = ?
            LIMIT 1
            """
            results = self.sqlite.execute_query(query, (normalized_path,))

        if not results:
            return None

        row = results[0]
        metadata = json.loads(row['metadata']) if row['metadata'] else {}

        return ModelWithLocation(
            hash=row['hash'],
            file_size=row['file_size'],
            blake3_hash=row['blake3_hash'],
            sha256_hash=row['sha256_hash'],
            relative_path=row['relative_path'],
            filename=row['filename'],
            mtime=row['mtime'],
            last_seen=row['last_seen'],
            base_directory=row.get('base_directory'),
            metadata=metadata
        )

    def search(self, term: str, base_directory: Path | None = "USE_CURRENT") -> list[ModelWithLocation]:
        """Search for models by filename or path, optionally filtered by directory.

        Args:
            term: Search term to match against filename or path
            base_directory: Directory to filter by. Defaults to current_directory.
                          Pass None explicitly to search all directories.

        Returns:
            List of matching ModelWithLocation objects
        """
        if base_directory == "USE_CURRENT":
            base_directory = self.current_directory

        if base_directory:
            base_dir_str = str(base_directory.resolve())
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE (l.filename LIKE ? OR l.relative_path LIKE ?)
              AND l.base_directory = ?
            ORDER BY l.filename
            """
            search_pattern = f"%{term}%"
            results = self.sqlite.execute_query(query, (search_pattern, search_pattern, base_dir_str))
        else:
            query = """
            SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
                   l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
            FROM models m
            JOIN model_locations l ON m.hash = l.model_hash
            WHERE l.filename LIKE ? OR l.relative_path LIKE ?
            ORDER BY l.filename
            """
            search_pattern = f"%{term}%"
            results = self.sqlite.execute_query(query, (search_pattern, search_pattern))

        models = []
        for row in results:
            metadata = json.loads(row['metadata']) if row['metadata'] else {}
            model = ModelWithLocation(
                hash=row['hash'],
                file_size=row['file_size'],
                blake3_hash=row['blake3_hash'],
                sha256_hash=row['sha256_hash'],
                relative_path=row['relative_path'],
                filename=row['filename'],
                mtime=row['mtime'],
                last_seen=row['last_seen'],
                base_directory=row.get('base_directory'),
                metadata=metadata
            )
            models.append(model)

        return models

    def clear_orphaned_models(self) -> int:
        """Remove models that have no file locations.

        When switching directories, models from the old directory may no longer
        have any valid locations. This method cleans up such orphaned records.

        Returns:
            Number of orphaned models removed
        """
        query = """
        DELETE FROM models
        WHERE hash NOT IN (SELECT DISTINCT model_hash FROM model_locations)
        """
        rows_affected = self.sqlite.execute_write(query)

        if rows_affected > 0:
            logger.info(f"Removed {rows_affected} orphaned models with no locations")

        return rows_affected

    def clear_orphaned_model_sources(self) -> int:
        """Remove model sources whose model record no longer exists.

        SQLite foreign-key cascading is not guaranteed for every connection used
        by this repository, so cleanup is explicit.
        """
        query = """
        DELETE FROM model_sources
        WHERE model_hash NOT IN (SELECT hash FROM models)
        """
        rows_affected = self.sqlite.execute_write(query)

        if rows_affected > 0:
            logger.info(f"Removed {rows_affected} orphaned model sources")

        return rows_affected

    def find_by_source_url(self, url: str) -> ModelWithLocation | None:
        """Find model by exact source URL match.

        Args:
            url: Source URL to search for

        Returns:
            ModelWithLocation if found, None otherwise
        """
        query = """
        SELECT m.hash, m.file_size, m.blake3_hash, m.sha256_hash, m.metadata,
               l.base_directory, l.relative_path, l.filename, l.mtime, l.last_seen
        FROM models m
        JOIN model_locations l ON m.hash = l.model_hash
        JOIN model_sources s ON m.hash = s.model_hash
        WHERE s.source_url = ?
        LIMIT 1
        """

        results = self.sqlite.execute_query(query, (url,))
        if not results:
            return None

        row = results[0]
        metadata = json.loads(row['metadata']) if row['metadata'] else {}

        return ModelWithLocation(
            hash=row['hash'],
            file_size=row['file_size'],
            blake3_hash=row['blake3_hash'],
            sha256_hash=row['sha256_hash'],
            relative_path=row['relative_path'],
            filename=row['filename'],
            mtime=row['mtime'],
            last_seen=row['last_seen'],
            base_directory=row.get('base_directory'),
            metadata=metadata
        )
