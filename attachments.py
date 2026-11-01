"""Read user-selected files for provider-supported multimodal messages."""

import base64
import mimetypes
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit


IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
TEXT_SUFFIXES = {
    ".txt", ".md", ".csv", ".json", ".xml", ".html", ".py", ".js",
    ".ts", ".css", ".java", ".rs", ".cpp", ".c", ".h", ".sql", ".yaml", ".yml",
}
MAX_BYTES = 20 * 1024 * 1024
FILE_SUFFIXES = "|".join(
    suffix.lstrip(".") for suffix in sorted(
        {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", *TEXT_SUFFIXES}
    )
)
FILE_URL = re.compile(r"file:///[^\s<>\"']+", re.IGNORECASE)
WINDOWS_PATH = re.compile(
    rf"(?<![\w])([A-Za-z]:\\(?:[^<>:\"|?*\r\n]+\\)*[^<>:\"|?*\r\n]*?\.(?:{FILE_SUFFIXES}))",
    re.IGNORECASE,
)


class AttachmentError(ValueError):
    pass


def local_file_references(text: str) -> tuple[str, list[str]]:
    paths = []
    cleaned = text
    for match in FILE_URL.finditer(text):
        source = unquote(urlsplit(match.group(0)).path).lstrip("/")
        path = Path(source)
        if path.is_file():
            paths.append(str(path))
            cleaned = cleaned.replace(match.group(0), " ")
    for match in list(WINDOWS_PATH.finditer(cleaned)):
        path = Path(match.group(1))
        if path.is_file():
            paths.append(str(path))
            cleaned = cleaned.replace(match.group(1), " ")
    return " ".join(cleaned.split()), paths


def load_files(paths: list[str], existing: list[dict] | None = None) -> list[dict]:
    result = list(existing or [])
    total = sum(len(item.get("data", "")) * 3 // 4 for item in result)
    for path_string in paths:
        path = Path(path_string)
        if not path.is_file():
            raise AttachmentError("Attachment file not found")
        size = path.stat().st_size
        if total + size > MAX_BYTES:
            raise AttachmentError("Attachments may not exceed 20 MB in total")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if mime in IMAGE_TYPES:
            kind = "image"
        elif mime == "application/pdf" or path.suffix.lower() == ".pdf":
            kind = "pdf"
            mime = "application/pdf"
        elif path.suffix.lower() in TEXT_SUFFIXES:
            kind = "text"
            mime = "text/plain"
        else:
            raise AttachmentError("Supported attachments: images, PDF, and text/code files")
        data = path.read_bytes()
        if kind == "text":
            try:
                data.decode("utf-8-sig")
            except UnicodeDecodeError as error:
                raise AttachmentError("Text attachments must be UTF-8") from error
        result.append({
            "name": path.name, "kind": kind, "mime": mime,
            "data": base64.b64encode(data).decode("ascii"),
        })
        total += size
    return result
