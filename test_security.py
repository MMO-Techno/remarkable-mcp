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
