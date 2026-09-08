import hashlib
import mimetypes
import re
from pathlib import Path

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".md", ".txt", ".html", ".htm", ".csv"}


def extract_text(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".csv":
        return path.read_text(encoding="utf-8-sig", errors="ignore")
    if suffix in {".html", ".htm"}:
        from trafilatura import extract

        html = path.read_text(encoding="utf-8", errors="ignore")
        return extract(html, include_links=False, include_images=False) or ""
    if suffix == ".pdf":
        from pypdf import PdfReader

        return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)
    if suffix == ".docx":
        from docx import Document

        return "\n".join(p.text for p in Document(path).paragraphs)
    raise ValueError(f"不支持的文档格式：{suffix}")


def split_text(text: str, chunk_size: int = 800, overlap: int = 120) -> list[dict]:
    if chunk_size < 100 or overlap < 0 or overlap >= chunk_size:
        raise ValueError("分片参数不合法")
    cleaned = re.sub(r"\n{3,}", "\n\n", text).strip()
    chunks: list[dict] = []
    start = 0
    while start < len(cleaned):
        hard_end = min(start + chunk_size, len(cleaned))
        end = hard_end
        if hard_end < len(cleaned):
            candidates = [
                cleaned.rfind(separator, start + chunk_size // 2, hard_end)
                for separator in ("\n\n", "。", "！", "？", ";", "；", "\n")
            ]
            boundary = max(candidates)
            if boundary > start:
                end = boundary + 1
        content = cleaned[start:end].strip()
        if content:
            chunks.append(
                {
                    "content": content,
                    "content_hash": hashlib.sha256(content.encode()).hexdigest(),
                    "metadata": {},
                }
            )
        if end == len(cleaned):
            break
        start = max(end - overlap, start + 1)
    return chunks


def file_metadata(path: str | Path) -> tuple[str, str | None]:
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest, mimetypes.guess_type(path.name)[0]
