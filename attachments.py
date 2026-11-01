"""Read user-selected files for provider-supported multimodal messages."""

import base64
import mimetypes
from pathlib import Path


IMAGE_TYPES = {"image/png", "image/jpeg", "image/gif", "image/webp"}
TEXT_SUFFIXES = {
    ".txt", ".md", ".csv", ".json", ".xml", ".html", ".py", ".js",
    ".ts", ".css", ".java", ".rs", ".cpp", ".c", ".h", ".sql", ".yaml", ".yml",
}
MAX_BYTES = 20 * 1024 * 1024


class AttachmentError(ValueError):
    pass


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
