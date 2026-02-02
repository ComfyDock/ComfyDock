"""One-time migration to normalize path separators in existing databases."""
from pathlib import Path

from .model_repository import ModelRepository


def migrate_path_separators(db_path: Path) -> int:
    """Normalize all path separators in model_locations to forward slashes.

    Args:
        db_path: Path to models.db database

    Returns:
        Number of paths updated
    """
    repo = ModelRepository(db_path)

    # Get all locations - we'll filter in Python to avoid SQL escaping issues
    query = """
    SELECT model_hash, base_directory, relative_path, filename, mtime
    FROM model_locations
    """

    all_results = repo.sqlite.execute_query(query)

    # Filter for paths with backslashes
    results = [r for r in all_results if '\\' in r['relative_path']]

    if not results:
        return 0

    # Update each path
    update_query = """
    UPDATE model_locations
    SET relative_path = ?
    WHERE model_hash = ? AND base_directory = ? AND relative_path = ?
    """

    count = 0
    for row in results:
        old_path = row['relative_path']
        new_path = old_path.replace('\\', '/')

        repo.sqlite.execute_write(
            update_query,
            (new_path, row['model_hash'], row['base_directory'], old_path)
        )
        count += 1

    return count
