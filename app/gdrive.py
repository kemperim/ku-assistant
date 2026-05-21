"""
Google Drive document downloader.
Supports:
  - Public shared files/folders (no auth needed)
  - Private files via Service Account JSON
"""

import os
import re
import logging
import aiohttp
import asyncio
from pathlib import Path
from typing import List, Dict

logger = logging.getLogger(__name__)

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt"}


def extract_ids_from_config(gdrive_ids: str) -> List[str]:
    """Parse comma-separated Drive IDs."""
    if not gdrive_ids.strip():
        return []
    return [x.strip() for x in gdrive_ids.split(",") if x.strip()]


def extract_id_from_url(url_or_id: str) -> str:
    """Extract file/folder ID from a Google Drive URL or return as-is."""
    patterns = [
        r"/folders/([a-zA-Z0-9_-]+)",
        r"/file/d/([a-zA-Z0-9_-]+)",
        r"id=([a-zA-Z0-9_-]+)",
    ]
    for pat in patterns:
        m = re.search(pat, url_or_id)
        if m:
            return m.group(1)
    # If it looks like a plain ID already
    if re.match(r"^[a-zA-Z0-9_-]{10,}$", url_or_id):
        return url_or_id
    return url_or_id


async def download_public_file(session: aiohttp.ClientSession, file_id: str, dest_path: Path) -> bool:
    """Download a single public Google Drive file."""
    url = f"https://drive.google.com/uc?export=download&id={file_id}&confirm=t"
    try:
        async with session.get(url, allow_redirects=True) as resp:
            if resp.status != 200:
                logger.warning(f"Failed to download file {file_id}: HTTP {resp.status}")
                return False
            content = await resp.read()
            if len(content) < 100:
                logger.warning(f"File {file_id} too small, likely an error page")
                return False
            dest_path.write_bytes(content)
            logger.info(f"Downloaded {file_id} -> {dest_path}")
            return True
    except Exception as e:
        logger.error(f"Error downloading {file_id}: {e}")
        return False


async def list_public_folder(session: aiohttp.ClientSession, folder_id: str) -> List[Dict]:
    """
    List files in a public Google Drive folder using the export trick.
    Returns list of {id, name} dicts.
    """
    files = []
    # Use the Drive API v3 public list endpoint (no key needed for public folders)
    # Fallback: scrape the folder HTML page
    url = f"https://drive.google.com/drive/folders/{folder_id}"
    try:
        async with session.get(url) as resp:
            text = await resp.text()
        # Extract file IDs from the folder page HTML
        # Pattern: ["filename","","","file_id"
        matches = re.findall(r'"([^"]+\.(pdf|docx|doc|txt))".*?"([a-zA-Z0-9_-]{25,})"', text)
        seen = set()
        for m in matches:
            fid = m[2]
            fname = m[0]
            if fid not in seen:
                seen.add(fid)
                files.append({"id": fid, "name": fname})
        if not files:
            # Alternative pattern
            ids = re.findall(r'["\s]([a-zA-Z0-9_-]{33})["\s]', text)
            names = re.findall(r'"([\w\s\-\.]+\.(pdf|docx|doc|txt))"', text)
            for i, (name_match) in enumerate(names):
                if i < len(ids):
                    files.append({"id": ids[i], "name": name_match[0]})
    except Exception as e:
        logger.error(f"Error listing folder {folder_id}: {e}")
    return files


async def download_with_service_account(
    ids: List[str], docs_path: Path, service_account_json: str
) -> List[Path]:
    """Download files using Google Drive API with service account."""
    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaIoBaseDownload
        import io
        import json

        creds_data = json.loads(service_account_json) if service_account_json.startswith("{") \
            else json.loads(Path(service_account_json).read_text())

        creds = service_account.Credentials.from_service_account_info(
            creds_data,
            scopes=["https://www.googleapis.com/auth/drive.readonly"],
        )
        service = build("drive", "v3", credentials=creds)
        downloaded = []

        async def _process_id(item_id: str):
            try:
                meta = service.files().get(fileId=item_id, fields="id,name,mimeType").execute()
                mime = meta.get("mimeType", "")

                if "folder" in mime:
                    # List folder contents
                    results = service.files().list(
                        q=f"'{item_id}' in parents and trashed=false",
                        fields="files(id,name,mimeType)",
                    ).execute()
                    for f in results.get("files", []):
                        ext = Path(f["name"]).suffix.lower()
                        if ext in SUPPORTED_EXTENSIONS:
                            await _download_file(f["id"], f["name"])
                else:
                    ext = Path(meta["name"]).suffix.lower()
                    if ext in SUPPORTED_EXTENSIONS:
                        await _download_file(item_id, meta["name"])
            except Exception as e:
                logger.error(f"Service account error for {item_id}: {e}")

        async def _download_file(fid: str, fname: str):
            dest = docs_path / fname
            if dest.exists():
                logger.info(f"Already exists: {fname}, skipping")
                downloaded.append(dest)
                return
            request = service.files().get_media(fileId=fid)
            buf = io.BytesIO()
            dl = MediaIoBaseDownload(buf, request)
            done = False
            while not done:
                _, done = dl.next_chunk()
            dest.write_bytes(buf.getvalue())
            logger.info(f"SA downloaded: {fname}")
            downloaded.append(dest)

        for item_id in ids:
            await _process_id(item_id)

        return downloaded
    except ImportError:
        logger.error("google-api-python-client not installed. Falling back to public download.")
        return []


async def sync_gdrive(gdrive_ids: str, docs_path: str, service_account_json: str = "") -> List[Path]:
    """
    Main entry point: sync Google Drive documents to local docs_path.
    Returns list of downloaded file paths.
    """
    docs_dir = Path(docs_path)
    docs_dir.mkdir(parents=True, exist_ok=True)

    raw_ids = extract_ids_from_config(gdrive_ids)
    if not raw_ids:
        logger.warning("No Google Drive IDs configured. Skipping sync.")
        return []

    ids = [extract_id_from_url(x) for x in raw_ids]
    downloaded = []

    # Try service account first if configured
    if service_account_json:
        logger.info("Using Service Account for Google Drive access")
        downloaded = await download_with_service_account(ids, docs_dir, service_account_json)
        if downloaded:
            return downloaded

    # Fallback: public download
    logger.info("Using public Google Drive download")
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector) as session:
        for item_id in ids:
            # Try as direct file first
            # Determine if it's a folder by checking the URL pattern
            # We'll try file download first; if it fails or is tiny, try folder listing
            test_dest = docs_dir / f"_test_{item_id}.bin"
            success = await download_public_file(session, item_id, test_dest)

            if success and test_dest.exists():
                # Detect real extension from content
                content = test_dest.read_bytes()
                if content[:4] == b'%PDF':
                    real_dest = docs_dir / f"{item_id}.pdf"
                    test_dest.rename(real_dest)
                    downloaded.append(real_dest)
                elif content[:2] == b'PK':  # ZIP = docx
                    real_dest = docs_dir / f"{item_id}.docx"
                    test_dest.rename(real_dest)
                    downloaded.append(real_dest)
                else:
                    # Might be a folder page or error
                    test_dest.unlink(missing_ok=True)
                    logger.info(f"Treating {item_id} as folder, listing contents...")
                    folder_files = await list_public_folder(session, item_id)
                    for f in folder_files:
                        fname = f["name"]
                        ext = Path(fname).suffix.lower()
                        if ext not in SUPPORTED_EXTENSIONS:
                            continue
                        dest = docs_dir / fname
                        if dest.exists():
                            logger.info(f"Skip existing: {fname}")
                            downloaded.append(dest)
                            continue
                        ok = await download_public_file(session, f["id"], dest)
                        if ok:
                            downloaded.append(dest)
            else:
                test_dest.unlink(missing_ok=True)
                # Try as folder
                folder_files = await list_public_folder(session, item_id)
                for f in folder_files:
                    fname = f["name"]
                    ext = Path(fname).suffix.lower()
                    if ext not in SUPPORTED_EXTENSIONS:
                        continue
                    dest = docs_dir / fname
                    if dest.exists():
                        downloaded.append(dest)
                        continue
                    ok = await download_public_file(session, f["id"], dest)
                    if ok:
                        downloaded.append(dest)

    logger.info(f"Total downloaded: {len(downloaded)} files")
    return downloaded
