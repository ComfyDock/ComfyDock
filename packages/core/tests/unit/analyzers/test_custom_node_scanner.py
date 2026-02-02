"""Unit tests for CustomNodeScanner requirements parsing."""
import tempfile
from pathlib import Path

from comfygit_core.analyzers.custom_node_scanner import CustomNodeScanner


class TestReadRequirements:
    """Unit tests for CustomNodeScanner._read_requirements()."""

    def test_strips_inline_comments(self):
        """Inline comments should be stripped from requirement lines."""
        scanner = CustomNodeScanner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("pillow>=8.0.0  # Image processing\n")
            temp_path = Path(f.name)

        try:
            result = scanner._read_requirements(temp_path)
            assert result == ["pillow>=8.0.0"]
        finally:
            temp_path.unlink()

    def test_strips_inline_comments_various_formats(self):
        """Various inline comment formats should all be handled."""
        scanner = CustomNodeScanner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("numpy # array processing\n")
            f.write("requests  # HTTP client\n")
            f.write("torch>=1.9.0 # deep learning\n")
            f.write("pillow[extra]>=8.0 # with extras\n")
            temp_path = Path(f.name)

        try:
            result = scanner._read_requirements(temp_path)
            assert result == [
                "numpy",
                "requests",
                "torch>=1.9.0",
                "pillow[extra]>=8.0"
            ]
        finally:
            temp_path.unlink()

    def test_ignores_full_line_comments(self):
        """Lines starting with # should be completely ignored."""
        scanner = CustomNodeScanner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("# This is a comment\n")
            f.write("numpy>=1.20.0\n")
            f.write("# Another comment\n")
            f.write("requests>=2.25.0\n")
            temp_path = Path(f.name)

        try:
            result = scanner._read_requirements(temp_path)
            assert result == ["numpy>=1.20.0", "requests>=2.25.0"]
        finally:
            temp_path.unlink()

    def test_handles_empty_lines(self):
        """Empty lines should be ignored."""
        scanner = CustomNodeScanner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("numpy>=1.20.0\n")
            f.write("\n")
            f.write("requests>=2.25.0\n")
            f.write("   \n")
            f.write("pillow\n")
            temp_path = Path(f.name)

        try:
            result = scanner._read_requirements(temp_path)
            assert result == ["numpy>=1.20.0", "requests>=2.25.0", "pillow"]
        finally:
            temp_path.unlink()

    def test_discards_lines_that_become_empty_after_stripping(self):
        """Lines that are only comments should not produce empty requirements."""
        scanner = CustomNodeScanner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("numpy>=1.20.0\n")
            f.write("  # only comment\n")
            f.write("requests>=2.25.0\n")
            temp_path = Path(f.name)

        try:
            result = scanner._read_requirements(temp_path)
            # The middle line is a full-line comment (starts with #) so it's skipped
            assert result == ["numpy>=1.20.0", "requests>=2.25.0"]
        finally:
            temp_path.unlink()

    def test_handles_requirements_without_version_specifiers(self):
        """Simple package names without versions should work."""
        scanner = CustomNodeScanner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("numpy\n")
            f.write("requests # with comment\n")
            f.write("pillow\n")
            temp_path = Path(f.name)

        try:
            result = scanner._read_requirements(temp_path)
            assert result == ["numpy", "requests", "pillow"]
        finally:
            temp_path.unlink()

    def test_empty_file_returns_empty_list(self):
        """An empty requirements file should return empty list."""
        scanner = CustomNodeScanner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("")
            temp_path = Path(f.name)

        try:
            result = scanner._read_requirements(temp_path)
            assert result == []
        finally:
            temp_path.unlink()

    def test_file_with_only_comments_returns_empty_list(self):
        """A file with only comments should return empty list."""
        scanner = CustomNodeScanner()

        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write("# Comment 1\n")
            f.write("# Comment 2\n")
            f.write("\n")
            temp_path = Path(f.name)

        try:
            result = scanner._read_requirements(temp_path)
            assert result == []
        finally:
            temp_path.unlink()

    def test_nonexistent_file_returns_empty_list(self):
        """A nonexistent file should return empty list without raising."""
        scanner = CustomNodeScanner()
        result = scanner._read_requirements(Path("/nonexistent/file.txt"))
        assert result == []
