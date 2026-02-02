"""Unit tests for HuggingFace URL parser module."""


from comfygit_core.services.huggingface_url import parse_huggingface_url


class TestParseHuggingFaceUrl:
    """Test parse_huggingface_url function."""

    def test_repo_url(self):
        """Test parsing a base repo URL returns kind='repo'."""
        result = parse_huggingface_url("https://huggingface.co/microsoft/VibeVoice-1.5B")
        assert result.kind == "repo"
        assert result.repo_id == "microsoft/VibeVoice-1.5B"
        assert result.revision == "main"

    def test_tree_url(self):
        """Test parsing a /tree/ URL returns kind='repo'."""
        result = parse_huggingface_url("https://huggingface.co/microsoft/VibeVoice-1.5B/tree/main")
        assert result.kind == "repo"
        assert result.repo_id == "microsoft/VibeVoice-1.5B"
        assert result.revision == "main"

    def test_tree_url_with_revision(self):
        """Test parsing /tree/ URL with specific revision."""
        result = parse_huggingface_url("https://huggingface.co/owner/repo/tree/v1.0")
        assert result.kind == "repo"
        assert result.repo_id == "owner/repo"
        assert result.revision == "v1.0"

    def test_resolve_url(self):
        """Test parsing a /resolve/ URL returns kind='file'."""
        result = parse_huggingface_url(
            "https://huggingface.co/owner/repo/resolve/main/model.safetensors"
        )
        assert result.kind == "file"
        assert result.repo_id == "owner/repo"
        assert result.revision == "main"
        assert result.path_in_repo == "model.safetensors"

    def test_blob_url(self):
        """Test parsing a /blob/ URL returns kind='file'."""
        result = parse_huggingface_url(
            "https://huggingface.co/owner/repo/blob/main/model.safetensors"
        )
        assert result.kind == "file"
        assert result.repo_id == "owner/repo"
        assert result.path_in_repo == "model.safetensors"

    def test_resolve_url_with_subdirectory(self):
        """Test parsing /resolve/ URL with nested path."""
        result = parse_huggingface_url(
            "https://huggingface.co/owner/repo/resolve/main/subdir/model.safetensors"
        )
        assert result.kind == "file"
        assert result.path_in_repo == "subdir/model.safetensors"

    def test_short_domain_hf_co(self):
        """Test parsing hf.co short domain."""
        result = parse_huggingface_url("https://hf.co/owner/repo")
        assert result.kind == "repo"
        assert result.repo_id == "owner/repo"

    def test_non_hf_url(self):
        """Test non-HuggingFace URLs return kind='unknown'."""
        result = parse_huggingface_url("https://civitai.com/model/123")
        assert result.kind == "unknown"
        assert result.repo_id is None

    def test_empty_string(self):
        """Test empty string returns kind='unknown'."""
        result = parse_huggingface_url("")
        assert result.kind == "unknown"

    def test_datasets_url_ignored(self):
        """Test datasets URLs are ignored (MVP scope)."""
        result = parse_huggingface_url("https://huggingface.co/datasets/owner/repo")
        assert result.kind == "unknown"

    def test_spaces_url_ignored(self):
        """Test spaces URLs are ignored (MVP scope)."""
        result = parse_huggingface_url("https://huggingface.co/spaces/owner/repo")
        assert result.kind == "unknown"
