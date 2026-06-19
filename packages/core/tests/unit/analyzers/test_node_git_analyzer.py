from pathlib import Path

from comfygit_core.analyzers import node_git_analyzer


def test_get_node_git_info_uses_non_throwing_dirty_probe(monkeypatch, tmp_path: Path):
    node_path = tmp_path / "custom-node"
    node_path.mkdir()
    (node_path / ".git").mkdir()

    def fake_rev_parse(repo_path: Path, ref: str = "HEAD", abbrev_ref: bool = False) -> str | None:
        assert repo_path == node_path
        return "main" if abbrev_ref else "abc123"

    def fake_status_porcelain(repo_path: Path, *, check: bool = True):
        assert repo_path == node_path
        assert check is False
        return []

    monkeypatch.setattr(node_git_analyzer, "git_rev_parse", fake_rev_parse)
    monkeypatch.setattr(node_git_analyzer, "git_describe_tags", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        node_git_analyzer,
        "git_remote_get_url",
        lambda _repo_path: "https://github.com/example/custom-node.git",
    )
    monkeypatch.setattr(node_git_analyzer, "git_status_porcelain", fake_status_porcelain)

    git_info = node_git_analyzer.get_node_git_info(node_path)

    assert git_info is not None
    assert git_info.commit == "abc123"
    assert git_info.branch == "main"
    assert git_info.remote_url == "https://github.com/example/custom-node.git"
    assert git_info.github_owner == "example"
    assert git_info.github_repo == "custom-node"
    assert git_info.is_dirty is False
