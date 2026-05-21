"""
Parse PDF and DOCX files into text chunks.
"""

import re
import logging
from pathlib import Path
from typing import List, Dict
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class TextChunk:
    text: str
    source: str        # filename
    page: int          # page/section number
    chunk_idx: int     # chunk index within document


def parse_pdf(path: Path) -> List[Dict]:
    """Extract pages from PDF as list of {text, page}."""
    pages = []
    try:
        import pdfplumber
        with pdfplumber.open(str(path)) as pdf:
            for i, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                text = clean_text(text)
                if text.strip():
                    pages.append({"text": text, "page": i + 1})
    except Exception as e:
        logger.error(f"pdfplumber failed for {path}: {e}, trying pypdf fallback")
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            for i, page in enumerate(reader.pages):
                text = clean_text(page.extract_text() or "")
                if text.strip():
                    pages.append({"text": text, "page": i + 1})
        except Exception as e2:
            logger.error(f"pypdf also failed for {path}: {e2}")
    return pages


def parse_docx(path: Path) -> List[Dict]:
    """Extract paragraphs from DOCX grouped into pseudo-pages."""
    sections = []
    try:
        import docx
        doc = docx.Document(str(path))
        current_text = []
        section_num = 1
        char_count = 0
        for para in doc.paragraphs:
            text = para.text.strip()
            if not text:
                continue
            current_text.append(text)
            char_count += len(text)
            # Group ~2000 chars as one "page"
            if char_count >= 2000:
                sections.append({"text": clean_text("\n".join(current_text)), "page": section_num})
                section_num += 1
                current_text = []
                char_count = 0
        if current_text:
            sections.append({"text": clean_text("\n".join(current_text)), "page": section_num})
    except Exception as e:
        logger.error(f"Error parsing DOCX {path}: {e}")
    return sections


def parse_txt(path: Path) -> List[Dict]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        chunks = []
        for i, part in enumerate(split_into_chunks_by_chars(text, 2000)):
            chunks.append({"text": clean_text(part), "page": i + 1})
        return chunks
    except Exception as e:
        logger.error(f"Error parsing TXT {path}: {e}")
        return []


def clean_text(text: str) -> str:
    """Remove excessive whitespace and control characters."""
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"[^\S\n]+", " ", text)
    return text.strip()


def split_into_chunks_by_chars(text: str, size: int) -> List[str]:
    """Split text into chunks of approximately `size` characters."""
    words = text.split()
    chunks = []
    current = []
    count = 0
    for word in words:
        current.append(word)
        count += len(word) + 1
        if count >= size:
            chunks.append(" ".join(current))
            current = []
            count = 0
    if current:
        chunks.append(" ".join(current))
    return chunks


def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> List[str]:
    """Split text into overlapping chunks by words."""
    words = text.split()
    if not words:
        return []
    # Approximate words per chunk
    words_per_chunk = max(1, chunk_size // 6)  # ~6 chars per word avg
    overlap_words = max(0, overlap // 6)
    chunks = []
    start = 0
    while start < len(words):
        end = min(start + words_per_chunk, len(words))
        chunk = " ".join(words[start:end])
        if chunk.strip():
            chunks.append(chunk)
        if end >= len(words):
            break
        start = end - overlap_words
    return chunks


def parse_document(path: Path) -> List[Dict]:
    """Parse any supported document. Returns list of {text, page}."""
    ext = path.suffix.lower()
    if ext == ".pdf":
        return parse_pdf(path)
    elif ext in (".docx", ".doc"):
        return parse_docx(path)
    elif ext == ".txt":
        return parse_txt(path)
    else:
        logger.warning(f"Unsupported file type: {ext}")
        return []


def document_to_chunks(path: Path, chunk_size: int = 800, overlap: int = 100) -> List[TextChunk]:
    """Parse document and split into TextChunk objects."""
    pages = parse_document(path)
    chunks = []
    chunk_global_idx = 0
    for page_data in pages:
        text_chunks = chunk_text(page_data["text"], chunk_size, overlap)
        for chunk_text_str in text_chunks:
            if chunk_text_str.strip():
                chunks.append(TextChunk(
                    text=chunk_text_str,
                    source=path.name,
                    page=page_data["page"],
                    chunk_idx=chunk_global_idx,
                ))
                chunk_global_idx += 1
    return chunks
