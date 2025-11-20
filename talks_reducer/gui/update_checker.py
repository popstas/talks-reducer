"""Update checker for Windows GUI that queries GitHub releases."""

from __future__ import annotations

import re
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Optional, Tuple


def is_windows() -> bool:
    """Return True if running on Windows."""
    return sys.platform == "win32"


def fetch_latest_version() -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch the latest version from GitHub releases.

    Returns:
        Tuple of (version_string, error_message). If successful, version_string
        contains the version (e.g., "0.9.4") and error_message is None.
        If failed, version_string is None and error_message contains the error.
    """
    if not is_windows():
        return None, "Update checking is only available on Windows"

    try:
        # Follow redirect from /releases/latest to get the actual release page
        url = "https://github.com/popstas/talks-reducer/releases/latest"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Talks-Reducer-Update-Checker/1.0")

        with urllib.request.urlopen(req, timeout=10) as response:
            # Get the final URL after redirect
            final_url = response.geturl()

            # Extract version from URL like https://github.com/popstas/talks-reducer/releases/tag/v0.9.4
            match = re.search(r"/releases/tag/v([\d.]+)", final_url)
            if match:
                version = match.group(1)
                return version, None

            # Fallback: try to parse from HTML content
            html = response.read().decode("utf-8", errors="ignore")
            # Look for version in various places in the HTML
            patterns = [
                r'href="/popstas/talks-reducer/releases/tag/v([\d.]+)"',
                r'"/releases/tag/v([\d.]+)"',
                r"v([\d.]+)</a>",
            ]
            for pattern in patterns:
                match = re.search(pattern, html)
                if match:
                    version = match.group(1)
                    return version, None

            return None, "Could not parse version from GitHub releases page"

    except urllib.error.URLError as e:
        return None, f"Network error: {str(e)}"
    except Exception as e:
        return None, f"Error checking for updates: {str(e)}"


def compare_versions(current: str, latest: str) -> bool:
    """
    Compare two version strings.

    Args:
        current: Current version string (e.g., "0.9.5")
        latest: Latest version string (e.g., "0.9.4")

    Returns:
        True if latest is newer than current, False otherwise.
    """
    try:
        # Split version strings into parts
        current_parts = [int(x) for x in current.split(".")]
        latest_parts = [int(x) for x in latest.split(".")]

        # Pad with zeros to make same length
        max_len = max(len(current_parts), len(latest_parts))
        current_parts.extend([0] * (max_len - len(current_parts)))
        latest_parts.extend([0] * (max_len - len(latest_parts)))

        # Compare parts
        for c, l in zip(current_parts, latest_parts):
            if l > c:
                return True
            if l < c:
                return False

        return False  # Versions are equal
    except (ValueError, AttributeError):
        # If parsing fails, do string comparison
        return latest > current


def get_installer_url(version: str) -> str:
    """Construct the installer download URL for the given version."""
    return f"https://github.com/popstas/talks-reducer/releases/download/v{version}/talks-reducer-{version}-setup.exe"


def get_portable_url(version: str) -> str:
    """Construct the portable download URL for the given version."""
    return f"https://github.com/popstas/talks-reducer/releases/download/v{version}/talks-reducer-windows-{version}.zip"


def get_releases_page_url() -> str:
    """Return the releases page URL."""
    return "https://github.com/popstas/talks-reducer/releases"


def download_file(
    url: str,
    progress_callback: Optional[Callable[[int, int], None]] = None,
) -> Tuple[Optional[Path], Optional[str]]:
    """
    Download a file from the given URL with progress tracking.

    Args:
        url: URL to download from
        progress_callback: Optional callback function(bytes_downloaded, total_bytes)
            called during download. If total_bytes is -1, size is unknown.

    Returns:
        Tuple of (file_path, error_message). If successful, file_path contains
        the path to the downloaded file and error_message is None.
        If failed, file_path is None and error_message contains the error.
    """
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Talks-Reducer-Update-Checker/1.0")

        with urllib.request.urlopen(req, timeout=30) as response:
            # Get file size if available
            total_bytes = int(response.headers.get("Content-Length", -1))

            # Create temp file
            suffix = Path(url).suffix or ".exe"
            temp_file = tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix, dir=tempfile.gettempdir()
            )
            temp_path = Path(temp_file.name)

            try:
                downloaded = 0
                while True:
                    chunk = response.read(8192)  # 8KB chunks
                    if not chunk:
                        break
                    temp_file.write(chunk)
                    downloaded += len(chunk)

                    if progress_callback:
                        progress_callback(downloaded, total_bytes)

                temp_file.close()
                return temp_path, None

            except Exception as e:
                temp_file.close()
                if temp_path.exists():
                    temp_path.unlink()
                return None, f"Error writing file: {str(e)}"

    except urllib.error.URLError as e:
        return None, f"Network error: {str(e)}"
    except Exception as e:
        return None, f"Error downloading file: {str(e)}"
