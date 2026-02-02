"""Unit tests for SQLiteManager."""

import pytest
from comfygit_core.infrastructure.sqlite_manager import SQLiteManager
from comfygit_core.models.exceptions import ComfyDockError


def test_create_table_and_basic_operations(tmp_path):
    """Test table creation and basic CRUD operations."""
    db_path = tmp_path / "test.db"
    sqlite_mgr = SQLiteManager(db_path)

    # Create a test table
    schema = """
    CREATE TABLE test_items (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        value INTEGER
    )
    """
    sqlite_mgr.create_table(schema)

    # Verify table exists
    assert sqlite_mgr.table_exists("test_items")

    # Insert some data
    rows_affected = sqlite_mgr.execute_write(
        "INSERT INTO test_items (name, value) VALUES (?, ?)",
        ("item1", 42)
    )
    assert rows_affected == 1

    # Query data
    results = sqlite_mgr.execute_query(
        "SELECT name, value FROM test_items WHERE name = ?",
        ("item1",)
    )
    assert len(results) == 1
    assert results[0]['name'] == "item1"
    assert results[0]['value'] == 42


def test_multiple_operations_and_table_info(tmp_path):
    """Test multiple operations and table information."""
    db_path = tmp_path / "multi_test.db"
    sqlite_mgr = SQLiteManager(db_path)

    # Create table with multiple columns
    schema = """
    CREATE TABLE products (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        price REAL,
        category TEXT DEFAULT 'general'
    )
    """
    sqlite_mgr.create_table(schema)

    # Insert multiple items
    items = [("Product A", 29.99), ("Product B", 49.99), ("Product C", 19.99)]
    for name, price in items:
        sqlite_mgr.execute_write(
            "INSERT INTO products (name, price) VALUES (?, ?)",
            (name, price)
        )

    # Query all items
    all_products = sqlite_mgr.execute_query("SELECT * FROM products ORDER BY name")
    assert len(all_products) == 3
    assert all_products[0]['name'] == "Product A"
    assert all_products[0]['price'] == 29.99
    assert all_products[0]['category'] == 'general'

    # Get table info
    table_info = sqlite_mgr.get_table_info("products")
    assert len(table_info) == 4  # 4 columns
    column_names = [col['name'] for col in table_info]
    assert 'id' in column_names
    assert 'name' in column_names
    assert 'price' in column_names
    assert 'category' in column_names


def test_error_handling(tmp_path):
    """Test error handling for invalid operations."""
    db_path = tmp_path / "error_test.db"
    sqlite_mgr = SQLiteManager(db_path)

    # Test invalid SQL query
    with pytest.raises(ComfyDockError):
        sqlite_mgr.execute_query("INVALID SQL STATEMENT")

    # Test query on non-existent table
    with pytest.raises(ComfyDockError):
        sqlite_mgr.execute_query("SELECT * FROM non_existent_table")

    # Test invalid write operation
    with pytest.raises(ComfyDockError):
        sqlite_mgr.execute_write("INSERT INTO non_existent_table VALUES (1)")
