"""Unit tests for ModelRepository.calculate_short_hash using xxhash."""

import xxhash
from comfygit_core.repositories.model_repository import (
    MODEL_SHORT_HASH_ALGORITHM,
    calculate_model_short_hash,
    ModelRepository,
)


def test_calculate_short_hash_uses_xxhash(tmp_path):
    """Verify short hash is computed using xxhash, not blake3."""
    db_path = tmp_path / "test.db"
    repo = ModelRepository(db_path)

    # Create a test file
    test_file = tmp_path / "test_model.safetensors"
    test_content = b"x" * 1024 * 1024  # 1MB of data
    test_file.write_bytes(test_content)

    # Calculate hash using our implementation
    result = repo.calculate_short_hash(test_file)
    helper_result = calculate_model_short_hash(test_file)

    # Calculate expected hash using xxhash directly (same algorithm)
    file_size = test_file.stat().st_size
    hasher = xxhash.xxh3_128()
    hasher.update(str(file_size).encode())
    hasher.update(test_content)  # File is < 30MB, so only start chunk
    expected = hasher.hexdigest()[:16]

    assert MODEL_SHORT_HASH_ALGORITHM == "xxh3_128_sample_v1"
    assert result == helper_result
    assert result == expected, f"Expected xxhash result {expected}, got {result}"


def test_calculate_short_hash_samples_large_files(tmp_path):
    """Verify large files sample start, middle, and end chunks."""
    db_path = tmp_path / "test.db"
    repo = ModelRepository(db_path)

    # Create a 50MB file (> 30MB threshold for middle/end sampling)
    chunk_size = 5 * 1024 * 1024  # 5MB
    file_size = 50 * 1024 * 1024  # 50MB

    test_file = tmp_path / "large_model.safetensors"

    # Create file with distinct regions so we can verify sampling
    with open(test_file, "wb") as f:
        # Fill with zeros, then write distinct markers
        f.write(b"\x00" * file_size)
        f.seek(0)

        # Start region: 'A' bytes
        f.write(b"A" * chunk_size)

        # Middle region: 'B' bytes
        middle_start = file_size // 2 - chunk_size // 2
        f.seek(middle_start)
        f.write(b"B" * chunk_size)

        # End region: 'C' bytes
        f.seek(file_size - chunk_size)
        f.write(b"C" * chunk_size)

    result = repo.calculate_short_hash(test_file)
    helper_result = calculate_model_short_hash(test_file)

    # Compute expected hash manually using xxhash
    hasher = xxhash.xxh3_128()
    hasher.update(str(file_size).encode())

    with open(test_file, "rb") as f:
        # Start
        hasher.update(f.read(chunk_size))
        # Middle
        f.seek(file_size // 2 - chunk_size // 2)
        hasher.update(f.read(chunk_size))
        # End
        f.seek(-chunk_size, 2)
        hasher.update(f.read(chunk_size))

    expected = hasher.hexdigest()[:16]

    assert result == helper_result
    assert result == expected, f"Expected {expected}, got {result}"


def test_calculate_short_hash_returns_16_char_hex(tmp_path):
    """Verify hash output is 16 hex characters (64 bits)."""
    db_path = tmp_path / "test.db"
    repo = ModelRepository(db_path)

    test_file = tmp_path / "model.safetensors"
    test_file.write_bytes(b"test data" * 1000)

    result = repo.calculate_short_hash(test_file)

    assert len(result) == 16, f"Expected 16 chars, got {len(result)}"
    assert all(c in "0123456789abcdef" for c in result), "Should be hex string"


def test_calculate_short_hash_includes_file_size(tmp_path):
    """Verify file size is included as discriminator."""
    db_path = tmp_path / "test.db"
    repo = ModelRepository(db_path)

    # Two files with same content prefix but different sizes
    file1 = tmp_path / "small.safetensors"
    file2 = tmp_path / "large.safetensors"

    content = b"identical content" * 1000
    file1.write_bytes(content)
    file2.write_bytes(content + b"extra data" * 500)

    hash1 = repo.calculate_short_hash(file1)
    hash2 = repo.calculate_short_hash(file2)

    assert hash1 != hash2, "Different file sizes should produce different hashes"
