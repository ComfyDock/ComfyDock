"""Tests for PyTorch utility functions."""


from comfygit_core.utils.pytorch import extract_backend_from_version, get_pytorch_index_url


class TestExtractBackendFromVersion:
    """Tests for extract_backend_from_version function."""

    def test_extract_cuda_backend(self):
        """Should extract CUDA backend from version string."""
        assert extract_backend_from_version("2.9.0+cu128") == "cu128"
        assert extract_backend_from_version("2.6.0+cu121") == "cu121"
        assert extract_backend_from_version("2.5.0+cu118") == "cu118"

    def test_extract_rocm_backend(self):
        """Should extract ROCm backend from version string."""
        assert extract_backend_from_version("2.9.0+rocm6.3") == "rocm6.3"
        assert extract_backend_from_version("2.8.0+rocm6.2") == "rocm6.2"

    def test_extract_cpu_backend(self):
        """Should extract CPU backend from version string."""
        assert extract_backend_from_version("2.9.0+cpu") == "cpu"

    def test_extract_xpu_backend(self):
        """Should extract Intel XPU backend from version string."""
        assert extract_backend_from_version("2.9.0+xpu") == "xpu"

    def test_no_backend_suffix(self):
        """Should return None for versions without backend suffix."""
        assert extract_backend_from_version("2.9.0") is None
        assert extract_backend_from_version("2.6.0") is None

    def test_future_cuda_versions(self):
        """Should handle future CUDA versions not in hardcoded list."""
        assert extract_backend_from_version("3.0.0+cu130") == "cu130"
        assert extract_backend_from_version("3.0.0+cu140") == "cu140"


class TestGetPytorchIndexUrl:
    """Tests for get_pytorch_index_url function."""

    def test_cuda_backends(self):
        """Should generate correct URLs for CUDA backends."""
        assert get_pytorch_index_url("cu128") == "https://download.pytorch.org/whl/cu128"
        assert get_pytorch_index_url("cu121") == "https://download.pytorch.org/whl/cu121"
        assert get_pytorch_index_url("cu118") == "https://download.pytorch.org/whl/cu118"

    def test_rocm_backends(self):
        """Should generate correct URLs for ROCm backends."""
        assert get_pytorch_index_url("rocm6.3") == "https://download.pytorch.org/whl/rocm6.3"
        assert get_pytorch_index_url("rocm6.2") == "https://download.pytorch.org/whl/rocm6.2"

    def test_cpu_backend(self):
        """Should generate correct URL for CPU backend."""
        assert get_pytorch_index_url("cpu") == "https://download.pytorch.org/whl/cpu"

    def test_xpu_backend(self):
        """Should generate correct URL for Intel XPU backend."""
        assert get_pytorch_index_url("xpu") == "https://download.pytorch.org/whl/xpu"

    def test_future_backends(self):
        """Should generate URLs for future/unknown backends using same pattern."""
        # Future CUDA versions
        assert get_pytorch_index_url("cu130") == "https://download.pytorch.org/whl/cu130"
        assert get_pytorch_index_url("cu140") == "https://download.pytorch.org/whl/cu140"

        # Future ROCm versions
        assert get_pytorch_index_url("rocm6.4") == "https://download.pytorch.org/whl/rocm6.4"
        assert get_pytorch_index_url("rocm7.0") == "https://download.pytorch.org/whl/rocm7.0"


class TestIntegration:
    """Integration tests combining both functions."""

    def test_roundtrip_cuda(self):
        """Should extract backend and generate URL correctly for CUDA."""
        version = "2.9.0+cu128"
        backend = extract_backend_from_version(version)
        url = get_pytorch_index_url(backend)
        assert url == "https://download.pytorch.org/whl/cu128"

    def test_roundtrip_rocm(self):
        """Should extract backend and generate URL correctly for ROCm."""
        version = "2.9.0+rocm6.3"
        backend = extract_backend_from_version(version)
        url = get_pytorch_index_url(backend)
        assert url == "https://download.pytorch.org/whl/rocm6.3"

    def test_roundtrip_future_version(self):
        """Should work for future versions not in any hardcoded list."""
        version = "3.0.0+cu130"
        backend = extract_backend_from_version(version)
        assert backend == "cu130"
        url = get_pytorch_index_url(backend)
        assert url == "https://download.pytorch.org/whl/cu130"
