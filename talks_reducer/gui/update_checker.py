"""Update checker for the Windows and macOS GUI that queries GitHub releases."""

from __future__ import annotations

import re
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Tuple


def is_windows() -> bool:
    """Return True if running on Windows."""
    return sys.platform == "win32"


def is_macos() -> bool:
    """Return True if running on macOS."""
    return sys.platform == "darwin"


def is_update_check_supported() -> bool:
    """Return True if in-app update checking is available on this platform."""
    return is_windows() or is_macos()


def _build_ssl_context() -> Optional[ssl.SSLContext]:
    """Return an SSL context backed by certifi's CA bundle when available.

    Frozen macOS/Linux builds ship their own Python without the system CA
    certificates OpenSSL expects, so the default context raises
    ``CERTIFICATE_VERIFY_FAILED`` against GitHub. Preferring certifi's bundle —
    which is already present transitively via the HTTP stack — fixes the
    verification while still validating the certificate chain. Falling back to
    ``None`` lets ``urlopen`` use its platform default when certifi is missing.
    """

    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:  # pragma: no cover - certifi missing or unreadable bundle
        return None


def fetch_latest_version() -> Tuple[Optional[str], Optional[str]]:
    """
    Fetch the latest version from GitHub releases.

    Returns:
        Tuple of (version_string, error_message). If successful, version_string
        contains the version (e.g., "0.9.4") and error_message is None.
        If failed, version_string is None and error_message contains the error.
    """
    if not is_update_check_supported():
        return None, "Update checking is only available on Windows and macOS"

    try:
        # Follow redirect from /releases/latest to get the actual release page
        url = "https://github.com/popstas/talks-reducer/releases/latest"
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Talks-Reducer-Update-Checker/1.0")

        with urllib.request.urlopen(
            req, timeout=10, context=_build_ssl_context()
        ) as response:
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


def get_macos_app_url(version: str) -> str:
    """Construct the macOS .app zip download URL for the given version."""
    return (
        "https://github.com/popstas/talks-reducer/releases/download/"
        f"v{version}/talks-reducer-macos.app-{version}.zip"
    )


def get_brew_upgrade_command() -> str:
    """Return the Homebrew command that upgrades the macOS cask."""
    return "brew upgrade --cask talks-reducer"


def get_releases_page_url() -> str:
    """Return the releases page URL."""
    return "https://github.com/popstas/talks-reducer/releases"


@dataclass(frozen=True)
class UpdatePresentation:
    """Platform-specific presentation for an available update.

    Attributes:
        status_text: Message describing the available update.
        links: ``(label, url)`` pairs to render as clickable links.
        button_text: Text the check-updates button should display.
        enable_download: ``True`` when the button should launch the installer
            download (Windows), ``False`` when it should remain a plain
            "Check updates" button (macOS, where updates go through Homebrew).
    """

    status_text: str
    links: List[Tuple[str, str]] = field(default_factory=list)
    button_text: str = "Check updates"
    enable_download: bool = False


def build_update_message(
    version: str, platform: Optional[str] = None
) -> UpdatePresentation:
    """Build the platform-specific presentation for an available update.

    Args:
        version: The newer version string discovered on GitHub releases.
        platform: Platform identifier (defaults to ``sys.platform``). macOS
            ("darwin") points the user at Homebrew without offering an
            in-app installer download; every other supported platform keeps
            the Windows installer download UX.

    Returns:
        An :class:`UpdatePresentation` describing the status text, links, and
        button behavior for the given platform.
    """
    resolved_platform = sys.platform if platform is None else platform
    releases_url = get_releases_page_url()

    if resolved_platform == "darwin":
        brew_command = get_brew_upgrade_command()
        return UpdatePresentation(
            status_text=(
                f"New version {version} is available! " f"Update with: {brew_command}"
            ),
            links=[("Releases page", releases_url)],
            button_text="Check updates",
            enable_download=False,
        )

    return UpdatePresentation(
        status_text=f"New version {version} is available!",
        links=[
            ("Releases page", releases_url),
        ],
        button_text=f"Download {version}",
        enable_download=True,
    )


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

        with urllib.request.urlopen(
            req, timeout=30, context=_build_ssl_context()
        ) as response:
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
