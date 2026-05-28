"""Generic SQLite database operations utility."""

import sqlite3
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from ..logging.logging_config import get_logger
from ..models.exceptions import ComfyDockError
from ..utils.redaction import redact_sensitive_text

logger = get_logger(__name__)


class SQLiteManager:
    """Generic SQLite database manager with connection management."""

    def __init__(self, db_path: Path):
        """Initialize SQLite manager.

        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get database connection with context management.

        Yields:
            SQLite connection with row factory enabled

        Raises:
            ComfyDockError: If database connection fails
        """
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database error: {e}")
            raise ComfyDockError(f"Database operation failed: {e}") from e
        finally:
            if conn:
                conn.close()

    def execute_query(self, query: str, params: tuple = ()) -> list[dict[str, Any]]:
        """Execute SELECT query and return results.

        Args:
            query: SQL SELECT query
            params: Query parameters

        Returns:
            List of dictionaries representing rows

        Raises:
            ComfyDockError: If query execution fails
        """
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(query, params)
                rows = cursor.fetchall()
                return [dict(row) for row in rows]
            except sqlite3.Error as e:
                logger.error(
                    "Query execution failed: %s with params %s: %s",
                    query,
                    redact_sensitive_text(params),
                    e,
                )
                raise ComfyDockError(f"Query execution failed: {e}") from e

    def execute_write(self, query: str, params: tuple = ()) -> int:
        """Execute INSERT/UPDATE/DELETE query.

        Args:
            query: SQL write query
            params: Query parameters

        Returns:
            Number of affected rows

        Raises:
            ComfyDockError: If write operation fails
        """
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(query, params)
                conn.commit()
                return cursor.rowcount
            except sqlite3.Error as e:
                logger.error(
                    "Write operation failed: %s with params %s: %s",
                    query,
                    redact_sensitive_text(params),
                    e,
                )
                conn.rollback()
                raise ComfyDockError(f"Write operation failed: {e}") from e

    def create_table(self, schema: str) -> None:
        """Create table using schema SQL.

        Args:
            schema: CREATE TABLE SQL statement

        Raises:
            ComfyDockError: If table creation fails
        """
        with self.get_connection() as conn:
            try:
                cursor = conn.cursor()
                cursor.execute(schema)
                conn.commit()
                logger.debug("Table schema ensured")
            except sqlite3.Error as e:
                logger.error(f"Table creation failed: {schema}: {e}")
                raise ComfyDockError(f"Table creation failed: {e}") from e

    def begin_transaction(self) -> sqlite3.Connection:
        """Begin a transaction and return connection for manual management.

        Returns:
            SQLite connection with transaction started

        Note:
            Caller is responsible for commit/rollback and closing connection
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            conn.execute("BEGIN")
            return conn
        except sqlite3.Error as e:
            logger.error(f"Transaction start failed: {e}")
            raise ComfyDockError(f"Transaction start failed: {e}") from e

    def table_exists(self, table_name: str) -> bool:
        """Check if table exists in database.

        Args:
            table_name: Name of table to check

        Returns:
            True if table exists, False otherwise
        """
        query = "SELECT name FROM sqlite_master WHERE type='table' AND name=?"
        results = self.execute_query(query, (table_name,))
        return len(results) > 0

    def get_table_info(self, table_name: str) -> list[dict[str, Any]]:
        """Get table schema information.

        Args:
            table_name: Name of table

        Returns:
            List of column information dictionaries
        """
        query = f"PRAGMA table_info({table_name})"
        return self.execute_query(query)
