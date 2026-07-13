"""Tests for SharePoint file enumeration robustness.

Covers the fix for issue #135: a folder whose name contains a special
character (e.g. ``#``) must not abort the whole crawl, and subfolder
traversal must use item IDs rather than reconstructed paths.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import httpx
import pytest

from sharepoint_client import GRAPH_BASE, SharePointClient


def _make_client() -> SharePointClient:
    """Build a client without running __init__ (skips credential setup)."""
    client = object.__new__(SharePointClient)
    return client


def _http_404() -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://graph.microsoft.com")
    response = httpx.Response(404, request=request)
    return httpx.HTTPStatusError("Not Found", request=request, response=response)


class TestListFilesSpecialCharacters:
    def test_special_char_path_is_encoded(self):
        """A ``#`` in a scoped folder path must be percent-encoded in the URL."""
        client = _make_client()
        captured: list[str] = []

        def fake_get_all_pages(url, params=None):
            captured.append(url)
            return []

        client._get_all_pages = fake_get_all_pages  # type: ignore[assignment]

        client.list_files("drive1", folder_path="Submissions/Submission #1")

        assert captured, "expected a Graph children request"
        assert "%23" in captured[0]
        assert "Submission #1" not in captured[0]
        # Path separators must be preserved (not encoded).
        assert "Submissions/Submission" in captured[0]

    def test_404_on_folder_is_skipped(self):
        """A 404 for one folder returns [] instead of raising."""
        client = _make_client()

        def fake_get_all_pages(url, params=None):
            raise _http_404()

        client._get_all_pages = fake_get_all_pages  # type: ignore[assignment]

        result = client.list_files("drive1", folder_path="Broken #Folder")
        assert result == []

    def test_non_404_error_propagates(self):
        """Errors other than 404 must still bubble up."""
        client = _make_client()
        request = httpx.Request("GET", "https://graph.microsoft.com")
        response = httpx.Response(500, request=request)

        def fake_get_all_pages(url, params=None):
            raise httpx.HTTPStatusError("boom", request=request, response=response)

        client._get_all_pages = fake_get_all_pages  # type: ignore[assignment]

        with pytest.raises(httpx.HTTPStatusError):
            client.list_files("drive1", folder_path="anything")

    def test_subfolders_traversed_by_item_id(self):
        """Recursion into a special-char subfolder must use its item ID URL."""
        client = _make_client()
        requested: list[str] = []

        root_items = [
            {"id": "folderA", "name": "Submission #1", "folder": {}},
            {"id": "file1", "name": "root.pdf", "file": {}},
        ]
        child_items = [
            {"id": "file2", "name": "nested.docx", "file": {}},
        ]

        def fake_get_all_pages(url, params=None):
            requested.append(url)
            if url.endswith("/root/children"):
                return root_items
            if url.endswith("/items/folderA/children"):
                return child_items
            raise AssertionError(f"unexpected URL: {url}")

        client._get_all_pages = fake_get_all_pages  # type: ignore[assignment]

        files = client.list_files("drive1")

        # The subfolder is reached by item ID, never by its "#" name.
        assert f"{GRAPH_BASE}/drives/drive1/items/folderA/children" in requested
        assert all("Submission #1" not in u for u in requested)

        names = sorted(f["name"] for f in files)
        assert names == ["nested.docx", "root.pdf"]
