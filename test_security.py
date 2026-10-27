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


class TestTokenNotLeaked:
    def test_invalid_token_error_does_not_echo_token(self):
        from remarkable_mcp.sync import load_client_from_token

        secret = "not-a-jwt-SECRET-VALUE-0123456789"
        with pytest.raises(ValueError) as excinfo:
            load_client_from_token(secret)
        assert "Invalid token format" in str(excinfo.value)
        assert secret[:6] not in str(excinfo.value)


def _item(doc_id, name, parent="", is_folder=False):
    item = Mock()
    item.ID = doc_id
    item.VissibleName = name
    item.Parent = parent
    item.is_folder = is_folder
    return item


def _library():
    return [
        _item("work", "Work", is_folder=True),
        _item("sub", "Sub", parent="work", is_folder=True),
        _item("report", "Report", parent="work"),
        _item("private", "Private", is_folder=True),
        _item("secret", "Secret", parent="private"),
        _item("top", "Top Level"),
        _item("binned", "Binned", parent="trash"),
        _item("old", "Old", parent="trash", is_folder=True),
        _item("orphan", "Orphan", parent="old"),
    ]


class TestWriteToolRootPath:
    def _resolve(self, name, **kwargs):
        from remarkable_mcp.api import get_items_by_id
        from remarkable_mcp.write_tools import _resolve_document

        collection = _library()
        item = _resolve_document(name, collection, get_items_by_id(collection), **kwargs)
        return item.ID if item else None

    def _parent(self, path):
        from remarkable_mcp.api import get_items_by_id
        from remarkable_mcp.write_tools import _resolve_parent_id

        collection = _library()
        return _resolve_parent_id(path, get_items_by_id(collection), collection)

    def test_documents_resolve_relative_to_root(self, monkeypatch):
        monkeypatch.setenv("REMARKABLE_ROOT_PATH", "/Work")
        assert self._resolve("Report") == "report"
        assert self._resolve("/Report") == "report"
        assert self._resolve("report") == "report"
        assert self._resolve("Sub", folders_only=True) == "sub"

    @pytest.mark.parametrize(
        "name", ["Secret", "/Private/Secret", "Private", "Top Level", "Work", "/", ""]
    )
    def test_documents_outside_root_or_root_itself_do_not_resolve(self, monkeypatch, name):
        monkeypatch.setenv("REMARKABLE_ROOT_PATH", "Work/")
        assert self._resolve(name) is None

    def test_parent_folders_resolve_relative_to_root(self, monkeypatch):
        monkeypatch.setenv("REMARKABLE_ROOT_PATH", "/Work")
        assert self._parent("/") == "work"
        assert self._parent("") == "work"
        assert self._parent("/Sub") == "sub"
        assert self._parent("/Private") is None
        assert self._parent("/Work") is None

    def test_missing_root_folder_resolves_nothing(self, monkeypatch):
        monkeypatch.setenv("REMARKABLE_ROOT_PATH", "/Nope")
        assert self._parent("/") is None
        assert self._resolve("Report") is None

    def test_unscoped_behaviour_is_unchanged(self, monkeypatch):
        monkeypatch.delenv("REMARKABLE_ROOT_PATH", raising=False)
        assert self._parent("/") == ""
        assert self._parent("/Work/Sub") == "sub"
        assert self._resolve("Secret") == "secret"
        assert self._resolve("/Private/Secret") == "secret"
        assert self._resolve("Work") == "work"

    @pytest.mark.parametrize("name", ["Binned", "/Binned", "Old", "Orphan", "/Old/Orphan"])
    def test_trashed_items_never_match(self, monkeypatch, name):
        monkeypatch.delenv("REMARKABLE_ROOT_PATH", raising=False)
        assert self._resolve(name) is None

    def test_trashed_folder_is_not_a_destination(self, monkeypatch):
        monkeypatch.delenv("REMARKABLE_ROOT_PATH", raising=False)
        assert self._parent("/Old") is None


_TRANSPORT_ENV = (
    "REMARKABLE_USE_SSH",
    "REMARKABLE_USE_USB_WEB",
    "REMARKABLE_USE_LOCAL_DIR",
    "REMARKABLE_LOCAL_DIR",
    "REMARKABLE_READ_ONLY",
)


async def _call_write_tool(name, args, client, **env):
    """Register write tools under ``env`` (cloud mode by default) and call one."""
    import json

    from remarkable_mcp.server import mcp
    from remarkable_mcp.write_tools import register_write_tools

    clean = {k: v for k, v in os.environ.items() if k not in _TRANSPORT_ENV}
    clean.update(env)
    registered = dict(mcp._tool_manager._tools)
    with patch.dict(os.environ, clean, clear=True):
        try:
            register_write_tools()
            with patch("remarkable_mcp.write_tools.get_rmapi", return_value=client):
                result = await mcp.call_tool(name, args)
        finally:
            mcp._tool_manager._tools.clear()
            mcp._tool_manager._tools.update(registered)
    return json.loads(result.content[0].text)


class TestWriteToolRootPathDispatch:
    @pytest.mark.asyncio
    async def test_cloud_move_cannot_target_outside_root(self):
        client = Mock(spec=["get_meta_items", "move"])
        client.get_meta_items.return_value = _library()
        data = await _call_write_tool(
            "remarkable_move",
            {"document": "Secret", "dest_folder": "/"},
            client,
            REMARKABLE_ROOT_PATH="/Work",
        )
        assert data["_error"]["type"] == "document_not_found"
        assert "Secret" not in str(data["_error"].get("did_you_mean"))
        client.move.assert_not_called()

    @pytest.mark.asyncio
    async def test_cloud_move_into_root_uses_root_folder(self):
        client = Mock(spec=["get_meta_items", "move"])
        client.get_meta_items.return_value = _library()
        data = await _call_write_tool(
            "remarkable_move",
            {"document": "/Sub", "dest_folder": "/"},
            client,
            REMARKABLE_ROOT_PATH="/Work",
        )
        assert data["moved"] is True
        client.move.assert_called_once_with("sub", "work")

    @pytest.mark.asyncio
    async def test_cloud_mkdir_outside_root_is_refused(self):
        client = Mock(spec=["get_meta_items", "create_folder"])
        client.get_meta_items.return_value = _library()
        data = await _call_write_tool(
            "remarkable_mkdir",
            {"folder_name": "X", "parent": "/Private"},
            client,
            REMARKABLE_ROOT_PATH="/Work",
        )
        assert data["_error"]["type"] == "folder_not_found"
        client.create_folder.assert_not_called()

    @pytest.mark.asyncio
    async def test_cloud_delete_skips_trashed_name_match(self):
        client = Mock(spec=["get_meta_items", "delete"])
        client.get_meta_items.return_value = _library()
        data = await _call_write_tool(
            "remarkable_delete", {"document": "Binned"}, client, REMARKABLE_SKIP_CONFIRM="1"
        )
        assert data["_error"]["type"] == "document_not_found"
        client.delete.assert_not_called()

    @pytest.mark.asyncio
    async def test_usb_web_upload_refused_when_root_is_set(self, tmp_path):
        pdf = tmp_path / "a.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        with patch("remarkable_mcp.write_tools._upload_via_usb_web") as upload:
            data = await _call_write_tool(
                "remarkable_upload",
                {"file_path": str(pdf)},
                Mock(),
                REMARKABLE_USE_USB_WEB="1",
                REMARKABLE_ROOT_PATH="/Work",
            )
        assert data["_error"]["type"] == "root_path_unsupported"
        upload.assert_not_called()


def _upload_client():
    client = Mock(spec=["get_meta_items", "upload_document"])
    client.get_meta_items.return_value = []
    client.upload_document.return_value = Mock(id="new-doc")
    return client


class TestUploadLocalPathPolicy:
    async def _upload(self, path, client=None, **env):
        client = client or _upload_client()
        data = await _call_write_tool("remarkable_upload", {"file_path": str(path)}, client, **env)
        return data, client

    @pytest.mark.asyncio
    async def test_regular_pdf_uploads(self, tmp_path):
        pdf = tmp_path / "Paper.pdf"
        pdf.write_bytes(b"%PDF-1.4\n")
        data, client = await self._upload(pdf)
        assert data["uploaded"] is True
        client.upload_document.assert_called_once_with(b"%PDF-1.4\n", "Paper", "pdf", "")

    @posix_only
    @pytest.mark.asyncio
    async def test_symlink_named_pdf_to_other_file_is_refused(self, tmp_path):
        secret = tmp_path / "id_ed25519"
        secret.write_text("PRIVATE KEY")
        link = tmp_path / "innocent.pdf"
        link.symlink_to(secret)
        data, client = await self._upload(link)
        assert data["_error"]["type"] == "unsupported_format"
        client.upload_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_directory_is_refused(self, tmp_path):
        folder = tmp_path / "folder.pdf"
        folder.mkdir()
        data, client = await self._upload(folder)
        assert data["_error"]["type"] == "file_not_found"
        client.upload_document.assert_not_called()

    @pytest.mark.asyncio
    async def test_size_cap(self, tmp_path):
        pdf = tmp_path / "big.pdf"
        pdf.write_bytes(b"x" * 11)
        data, client = await self._upload(pdf, REMARKABLE_UPLOAD_MAX_BYTES="10")
        assert data["_error"]["type"] == "file_too_large"
        client.upload_document.assert_not_called()

    def test_size_cap_default_and_invalid_values(self, monkeypatch):
        from remarkable_mcp.write_tools import DEFAULT_UPLOAD_MAX_BYTES, _upload_max_bytes

        assert DEFAULT_UPLOAD_MAX_BYTES == 200 * 1024 * 1024
        for value in ("", "abc", "0", "-5"):
            monkeypatch.setenv("REMARKABLE_UPLOAD_MAX_BYTES", value)
            assert _upload_max_bytes() == DEFAULT_UPLOAD_MAX_BYTES
        monkeypatch.setenv("REMARKABLE_UPLOAD_MAX_BYTES", "1234")
        assert _upload_max_bytes() == 1234

    @pytest.mark.asyncio
    async def test_allowlist_refuses_outside_paths(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside = tmp_path / "allowed-not" / "a.pdf"
        outside.parent.mkdir()
        outside.write_bytes(b"%PDF")
        data, client = await self._upload(outside, REMARKABLE_UPLOAD_DIRS=str(allowed))
        assert data["_error"]["type"] == "upload_path_not_allowed"
        client.upload_document.assert_not_called()

    @posix_only
    @pytest.mark.asyncio
    async def test_allowlist_checks_symlink_target(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        target = tmp_path / "outside.pdf"
        target.write_bytes(b"%PDF")
        (allowed / "link.pdf").symlink_to(target)
        data, _ = await self._upload(allowed / "link.pdf", REMARKABLE_UPLOAD_DIRS=str(allowed))
        assert data["_error"]["type"] == "upload_path_not_allowed"

    @pytest.mark.asyncio
    async def test_allowlist_accepts_any_listed_dir(self, tmp_path):
        first, second = tmp_path / "one", tmp_path / "two"
        first.mkdir()
        second.mkdir()
        pdf = second / "sub" / "a.pdf"
        pdf.parent.mkdir()
        pdf.write_bytes(b"%PDF")
        dirs = os.pathsep.join([str(first), "", str(second)])
        data, _ = await self._upload(pdf, REMARKABLE_UPLOAD_DIRS=dirs)
        assert data["uploaded"] is True

    @pytest.mark.asyncio
    async def test_markdown_to_pdf_is_not_blocked_by_allowlist(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        client = _upload_client()
        data = await _call_write_tool(
            "remarkable_markdown_to_pdf",
            {"markdown": "# Hello", "document_name": "Hello"},
            client,
            REMARKABLE_UPLOAD_DIRS=str(allowed),
        )
        assert data["uploaded"] is True
        client.upload_document.assert_called_once()


class TestArchiveLimits:
    def _zip(self, path, members):
        import zipfile

        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, data in members:
                zf.writestr(name, data)
        return path

    def test_member_count_limit(self, monkeypatch, tmp_path):
        import zipfile

        from remarkable_mcp import extract

        monkeypatch.setattr(extract, "MAX_ARCHIVE_MEMBERS", 3)
        archive = self._zip(tmp_path / "a.zip", [(f"{i}.rm", b"x") for i in range(4)])
        with zipfile.ZipFile(archive) as zf, pytest.raises(ValueError, match="members"):
            extract.safe_extractall(zf, tmp_path / "out")
        assert not (tmp_path / "out").exists()

    def test_uncompressed_size_limit(self, monkeypatch, tmp_path):
        import zipfile

        from remarkable_mcp import extract

        monkeypatch.setattr(extract, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 1024)
        # Highly compressible payload: small on disk, large when expanded.
        archive = self._zip(tmp_path / "bomb.zip", [("page.rm", b"\0" * 4096)])
        assert archive.stat().st_size < 1024
        with zipfile.ZipFile(archive) as zf, pytest.raises(ValueError, match="expands"):
            extract.safe_extractall(zf, tmp_path / "out")

    def test_within_limits_extracts_and_blocks_zip_slip(self, tmp_path):
        import zipfile

        from remarkable_mcp import extract

        archive = self._zip(tmp_path / "a.zip", [("ok.rm", b"1"), ("../../evil.txt", b"2")])
        out = tmp_path / "deep" / "out"
        with zipfile.ZipFile(archive) as zf:
            extract.safe_extractall(zf, out)
        assert (out / "ok.rm").read_bytes() == b"1"
        assert (out / "evil.txt").read_bytes() == b"2"
        assert not (tmp_path / "evil.txt").exists()
        assert not (tmp_path / "deep" / "evil.txt").exists()

    def test_oversized_epub_is_not_parsed(self, monkeypatch, tmp_path):
        from remarkable_mcp import extract

        monkeypatch.setattr(extract, "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 10)
        epub = self._zip(tmp_path / "b.epub", [("mimetype", b"application/epub+zip" * 4)])
        with patch("ebooklib.epub.read_epub") as read_epub:
            assert extract.extract_text_from_epub(epub) == ""
        read_epub.assert_not_called()
