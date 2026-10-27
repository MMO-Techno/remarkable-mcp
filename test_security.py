"""Security hardening tests (credential and cache permissions, input validation)."""

import os
import stat
import sys
from unittest.mock import Mock, patch

import pytest

posix_only = pytest.mark.skipif(sys.platform == "win32", reason="POSIX permission bits")


def _mode(path) -> int:
    return stat.S_IMODE(os.stat(path).st_mode)


class TestTokenFilePermissions:
    @posix_only
    @patch("remarkable_mcp.sync.time.sleep")
    @patch("remarkable_mcp.sync._issue_request")
    def test_register_writes_token_owner_only(self, mock_request, _sleep, monkeypatch, tmp_path):
        from remarkable_mcp.api import register_and_get_token

        monkeypatch.setenv("HOME", str(tmp_path))
        token_file = tmp_path / ".rmapi"
        token_file.write_text("old")
        os.chmod(token_file, 0o644)
        mock_request.return_value = Mock(status_code=200, text="device-token")

        token = register_and_get_token("code")

        assert token_file.read_text() == token
        assert _mode(token_file) == 0o600
        assert [p.name for p in tmp_path.iterdir()] == [".rmapi"]

    @posix_only
    def test_write_private_file_ignores_permissive_umask(self, tmp_path):
        from remarkable_mcp.api import write_private_file

        old = os.umask(0)
        try:
            write_private_file(tmp_path / "secret", "x")
        finally:
            os.umask(old)
        assert _mode(tmp_path / "secret") == 0o600


class TestBlobCachePermissions:
    BLOB_HASH = "a" * 64

    def _client(self, mock_request, content=b"blob"):
        from remarkable_mcp.sync import RemarkableClient

        response = Mock(status_code=200, content=content, headers={})
        response.raise_for_status = Mock()
        mock_request.return_value = response
        return RemarkableClient(user_token="user-token")

    @posix_only
    @patch("remarkable_mcp.sync._http_request_with_retry")
    def test_default_cache_dirs_and_blobs_are_private(self, mock_request, monkeypatch, tmp_path):
        monkeypatch.delenv("REMARKABLE_CACHE_DIR", raising=False)
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / ".remarkable").mkdir(mode=0o755)
        client = self._client(mock_request)

        old = os.umask(0)
        try:
            client._get_file(self.BLOB_HASH, "a.docSchema")
        finally:
            os.umask(old)

        base = tmp_path / ".remarkable"
        for path in (base, base / "cache", base / "cache" / "blobs"):
            assert _mode(path) == 0o700, path
        blob = base / "cache" / "blobs" / self.BLOB_HASH
        assert blob.read_bytes() == b"blob"
        assert _mode(blob) == 0o600
        assert sorted(p.name for p in blob.parent.iterdir()) == [self.BLOB_HASH]

    @posix_only
    @patch("remarkable_mcp.sync._http_request_with_retry")
    def test_override_cache_dir_only_tightens_leaf(self, mock_request, monkeypatch, tmp_path):
        shared = tmp_path / "shared"
        shared.mkdir(mode=0o755)
        os.chmod(shared, 0o755)
        monkeypatch.setenv("REMARKABLE_CACHE_DIR", str(shared / "blobs"))
        client = self._client(mock_request)

        client._get_file(self.BLOB_HASH, "a.docSchema")

        assert _mode(shared) == 0o755
        assert _mode(shared / "blobs") == 0o700
        assert _mode(shared / "blobs" / self.BLOB_HASH) == 0o600


class TestBlobHashValidation:
    @pytest.mark.parametrize(
        "bad_hash",
        ["../../.rmapi", "A" * 64, "a" * 63, "a" * 65, "", "a" * 63 + "/", "g" * 64],
    )
    @patch("remarkable_mcp.sync._http_request_with_retry")
    def test_malformed_hash_is_refused_without_network_or_disk(
        self, mock_request, bad_hash, monkeypatch, tmp_path
    ):
        from remarkable_mcp.sync import RemarkableClient

        monkeypatch.setenv("REMARKABLE_CACHE_DIR", str(tmp_path / "blobs"))
        client = RemarkableClient(user_token="user-token")

        with pytest.raises(ValueError, match="malformed blob hash"):
            client._get_file(bad_hash, "x")

        mock_request.assert_not_called()
        assert not (tmp_path / "blobs").exists()

    def test_cache_helpers_ignore_malformed_hash(self, monkeypatch, tmp_path):
        from remarkable_mcp.sync import RemarkableClient

        monkeypatch.setenv("REMARKABLE_CACHE_DIR", str(tmp_path / "blobs"))
        client = RemarkableClient(user_token="user-token")
        client._cache_write("../escape", b"data")
        assert client._cache_read("../escape") is None
        assert not (tmp_path / "escape").exists()
        assert not (tmp_path / "blobs").exists()
