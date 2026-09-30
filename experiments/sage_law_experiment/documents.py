"""Lightweight Harvey LAB document extraction.

The benchmark contains mostly Office files and email exports. This module keeps
the experiment runner dependency-light by extracting enough plain text for model
context with Python's standard library.
"""

from __future__ import annotations

import html
import json
import re
import zipfile
from email import policy
from email.parser import BytesParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

LONG_TEXT_STOPWORDS = {
    "about",
    "after",
    "against",
    "also",
    "analysis",
    "and",
    "are",
    "before",
    "brief",
    "client",
    "deliverable",
    "draft",
    "from",
    "have",
    "into",
    "legal",
    "memo",
    "memorandum",
    "must",
    "other",
    "should",
    "task",
    "that",
    "their",
    "there",
    "this",
    "with",
    "work",
}

FAILURE_MODE_TERMS = {
    "source_support": ["source", "citation", "cite", "clause", "section", "document", "exhibit"],
    "jurisdiction_governing_law": ["jurisdiction", "governing", "forum", "venue", "delaware", "court"],
    "authority_status": ["authority", "controlling", "persuasive", "binding", "precedent", "statute"],
    "issue_coverage": ["issue", "risk", "notice", "requirement", "element", "defense", "claim"],
    "recommendation_authority": ["recommend", "recommendation", "should", "action", "review", "counsel"],
    "privilege_release_review": ["privilege", "confidential", "redact", "client", "release", "attorney"],
}

WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
WORD = f"{{{WORD_NS}}}"
DOCX_EXTRACTION_VERSION = "accepted-revisions-comments-v2"


def _xml_text(xml_bytes: bytes) -> str:
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return ""
    parts = [node.text for node in root.iter() if node.text and node.text.strip()]
    return " ".join(parts)


def _read_zip_xml(path: Path, members: list[str] | None = None, prefix: str | None = None) -> str:
    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = members or sorted(name for name in archive.namelist() if not prefix or name.startswith(prefix))
        for name in names:
            if name in archive.namelist() and name.endswith(".xml"):
                text = _xml_text(archive.read(name))
                if text:
                    parts.append(text)
    return "\n".join(parts)


def read_docx(path: Path) -> str:
    """Read the judge-visible accepted-revision view of a Word document.

    ``python-docx`` omits text nested under ``w:ins`` from ``paragraph.text``.
    That is catastrophic for redlines: the judge sees blank replacement clauses.
    Parse OOXML directly, include inserted/current text, exclude deleted/moved-from
    text, and expose tracked-change metadata and comments as separately labelled
    evidence.
    """

    try:
        with zipfile.ZipFile(path) as archive:
            document_xml = archive.read("word/document.xml")
            comments_xml = archive.read("word/comments.xml") if "word/comments.xml" in archive.namelist() else b""
    except (KeyError, OSError, zipfile.BadZipFile):
        return ""
    try:
        root = ElementTree.fromstring(document_xml)
    except ElementTree.ParseError:
        return ""

    accepted_paragraphs = [
        text
        for paragraph in root.iter(WORD + "p")
        if (text := _accepted_word_text(paragraph).strip())
    ]
    sections: list[str] = []
    accepted = "\n".join(accepted_paragraphs).strip()
    if accepted:
        sections.append(accepted)

    insertions = list(root.iter(WORD + "ins")) + list(root.iter(WORD + "moveTo"))
    deletions = list(root.iter(WORD + "del")) + list(root.iter(WORD + "moveFrom"))
    if insertions or deletions:
        revision_lines = [
            f"[Word tracked changes: insertions={len(insertions)}; deletions={len(deletions)}]"
        ]
        sections.append("\n".join(revision_lines))

    comments = _word_comments(comments_xml)
    if comments:
        comment_lines = ["[Word comments]"]
        for comment in comments:
            metadata = " ".join(
                part
                for part in (
                    f"id={comment['id']}" if comment["id"] else "",
                    f"author={comment['author']}" if comment["author"] else "",
                )
                if part
            )
            label = f"[Comment {metadata}]" if metadata else "[Comment]"
            comment_lines.append(f"{label} {comment['text']}")
        sections.append("\n".join(comment_lines))

    return "\n\n".join(section for section in sections if section).strip()


def _accepted_word_text(element: ElementTree.Element) -> str:
    parts: list[str] = []

    def visit(node: ElementTree.Element, *, excluded: bool = False) -> None:
        local = _word_local_name(node.tag)
        excluded = excluded or local in {"del", "moveFrom"}
        if excluded:
            return
        if local == "t":
            parts.append(node.text or "")
            return
        if local == "tab":
            parts.append("\t")
            return
        if local in {"br", "cr"}:
            parts.append("\n")
            return
        if local == "noBreakHyphen":
            parts.append("‑")
            return
        for child in node:
            visit(child, excluded=excluded)

    visit(element)
    return "".join(parts)


def _word_text_including_deleted(element: ElementTree.Element) -> str:
    parts: list[str] = []
    for node in element.iter():
        local = _word_local_name(node.tag)
        if local in {"t", "delText"}:
            parts.append(node.text or "")
        elif local == "tab":
            parts.append("\t")
        elif local in {"br", "cr"}:
            parts.append("\n")
    return "".join(parts)


def _word_comments(xml_bytes: bytes) -> list[dict[str, str]]:
    if not xml_bytes:
        return []
    try:
        root = ElementTree.fromstring(xml_bytes)
    except ElementTree.ParseError:
        return []
    comments: list[dict[str, str]] = []
    for comment in root.iter(WORD + "comment"):
        text = "\n".join(
            value
            for paragraph in comment.iter(WORD + "p")
            if (value := _word_text_including_deleted(paragraph).strip())
        ).strip()
        if not text:
            continue
        comments.append(
            {
                "id": str(comment.attrib.get(WORD + "id") or ""),
                "author": str(comment.attrib.get(WORD + "author") or ""),
                "text": text,
            }
        )
    return comments


def _word_local_name(tag: str) -> str:
    return str(tag).rsplit("}", 1)[-1]


def read_pptx(path: Path) -> str:
    try:
        from markitdown import MarkItDown

        result = MarkItDown().convert(str(path))
        if result.text_content:
            return result.text_content
    except Exception:
        pass
    return _read_zip_xml(path, prefix="ppt/slides/")


def read_xlsx(path: Path) -> str:
    try:
        import pandas as pd

        sheets = pd.read_excel(path, sheet_name=None)
        parts = []
        for sheet_name, frame in sheets.items():
            parts.append(f"## {sheet_name}")
            parts.append(frame.to_string(index=False))
        if parts:
            return "\n".join(parts)
    except Exception:
        pass
    parts: list[str] = []
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared_strings: list[str] = []
        if "xl/sharedStrings.xml" in names:
            try:
                root = ElementTree.fromstring(archive.read("xl/sharedStrings.xml"))
                shared_strings = [" ".join(t.text or "" for t in si.iter() if t.tag.endswith("}t") or t.tag == "t") for si in root]
            except ElementTree.ParseError:
                shared_strings = []
        for sheet_name in sorted(name for name in names if name.startswith("xl/worksheets/") and name.endswith(".xml")):
            try:
                root = ElementTree.fromstring(archive.read(sheet_name))
            except ElementTree.ParseError:
                continue
            rows: list[str] = []
            for row in root.iter():
                if not row.tag.endswith("}row") and row.tag != "row":
                    continue
                cells: list[str] = []
                for cell in row:
                    if not cell.tag.endswith("}c") and cell.tag != "c":
                        continue
                    cell_type = cell.attrib.get("t")
                    value = ""
                    for child in cell:
                        if child.tag.endswith("}v") or child.tag == "v":
                            value = child.text or ""
                        elif child.tag.endswith("}is") or child.tag == "is":
                            value = " ".join(t.text or "" for t in child.iter() if t.tag.endswith("}t") or t.tag == "t")
                    if cell_type == "s" and value.isdigit() and int(value) < len(shared_strings):
                        value = shared_strings[int(value)]
                    if value.strip():
                        cells.append(value.strip())
                if cells:
                    rows.append(" | ".join(cells))
            if rows:
                parts.append(f"## {Path(sheet_name).stem}\n" + "\n".join(rows))
    return "\n\n".join(parts)


def read_eml(path: Path) -> str:
    message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
    headers = []
    for key in ("From", "To", "Cc", "Subject", "Date"):
        value = message.get(key)
        if value:
            headers.append(f"{key}: {value}")
    body = ""
    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            if content_type == "text/plain":
                body += "\n" + str(part.get_content())
            elif content_type == "text/html" and not body:
                body += "\n" + re.sub(r"<[^>]+>", " ", html.unescape(str(part.get_content())))
    else:
        body = str(message.get_content())
    return "\n".join(headers) + "\n\n" + body


def read_document(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix == ".docx":
            return read_docx(path)
        if suffix == ".xlsx":
            return read_xlsx(path)
        if suffix == ".pptx":
            return read_pptx(path)
        if suffix == ".eml":
            return read_eml(path)
        if suffix == ".pdf":
            try:
                import pdfplumber

                parts = []
                with pdfplumber.open(path) as pdf:
                    for page in pdf.pages:
                        text = page.extract_text()
                        if text:
                            parts.append(text)
                return "\n".join(parts)
            except Exception:
                pass
        if suffix == ".json":
            return json.dumps(json.loads(path.read_text(errors="replace")), indent=2, sort_keys=True)
        return path.read_text(errors="replace")
    except Exception as exc:
        return f"(error extracting {path.name}: {exc})"


def context_query_terms(data: dict[str, Any]) -> list[str]:
    deliverables = data.get("deliverables") or {}
    deliverable_text = " ".join(deliverables.keys() if isinstance(deliverables, dict) else deliverables)
    criteria = data.get("criteria") or []
    criteria_text = " ".join(
        f"{criterion.get('title', '')} {criterion.get('match_criteria', '')}"
        for criterion in criteria
        if isinstance(criterion, dict)
    )
    raw = " ".join(
        [
            data.get("title", ""),
            data.get("work_type", ""),
            " ".join(data.get("tags") or []),
            data.get("instructions", ""),
            deliverable_text,
            criteria_text,
        ]
    ).lower()
    terms = [
        word
        for word in re.findall(r"[a-z][a-z0-9-]{3,}", raw)
        if word not in LONG_TEXT_STOPWORDS and not word.isdigit()
    ]
    for mode in infer_failure_modes_from_task_text(raw):
        terms.extend(FAILURE_MODE_TERMS.get(mode, []))
    counts: dict[str, int] = {}
    for term in terms:
        counts[term] = counts.get(term, 0) + 1
    return [
        term
        for term, _count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    ][:80]


def infer_failure_modes_from_task_text(text: str) -> list[str]:
    mode_patterns = {
        "source_support": r"\b(cite|citation|source|document|clause|section|support)\b",
        "jurisdiction_governing_law": r"\b(jurisdiction|governing law|forum|venue|delaware|court)\b",
        "authority_status": r"\b(controlling|persuasive|authority|precedent|statute|binding)\b",
        "issue_coverage": r"\b(issue|risk|identify|review|requirement|element)\b",
        "recommendation_authority": r"\b(recommend|should|action|remedy|motion|brief|letter)\b",
        "privilege_release_review": r"\b(client|memo|draft|filing|confidential|privilege|release)\b",
    }
    return [mode for mode, pattern in mode_patterns.items() if re.search(pattern, text, re.I)]


def chunk_text(text: str, chunk_chars: int, overlap_chars: int) -> list[tuple[int, int, str]]:
    compact = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not compact:
        return []
    chunk_chars = max(400, chunk_chars)
    overlap_chars = min(max(0, overlap_chars), chunk_chars // 3)
    chunks = []
    start = 0
    while start < len(compact):
        end = min(len(compact), start + chunk_chars)
        if end < len(compact):
            boundary = max(compact.rfind("\n\n", start, end), compact.rfind(". ", start, end))
            if boundary > start + chunk_chars // 2:
                end = boundary + 1
        chunks.append((start, end, compact[start:end].strip()))
        if end >= len(compact):
            break
        start = max(end - overlap_chars, start + 1)
    return chunks


def score_chunk(
    text: str,
    relative_path: str,
    query_terms: list[str],
    chunk_index: int,
) -> tuple[float, list[str]]:
    lower = text.lower()
    path_lower = relative_path.lower()
    matched = []
    score = 0.0
    for term in query_terms:
        occurrences = lower.count(term)
        path_hit = term in path_lower
        if occurrences or path_hit:
            matched.append(term)
            score += min(occurrences, 4) + (1.5 if path_hit else 0)
    if re.search(r"\b(section|clause|exhibit|schedule|agreement|notice|governing law|court|authority)\b", lower):
        score += 3.0
    if chunk_index == 0:
        score += 0.75
    return score, matched[:20]


def load_full_context(
    task_dir: Path,
    data: dict[str, Any],
    max_documents: int,
    max_document_chars: int,
    max_context_chars: int,
) -> dict[str, Any]:
    documents = []
    total_chars = 0
    for path in sorted((task_dir / "documents").rglob("*")):
        if not path.is_file():
            continue
        if max_documents > 0 and len(documents) >= max_documents:
            break
        text = read_document(path)
        original_chars = len(text)
        if max_document_chars > 0:
            text = text[:max_document_chars]
        if total_chars + len(text) > max_context_chars:
            text = text[: max(0, max_context_chars - total_chars)]
        documents.append({
            "filename": path.name,
            "relative_path": str(path.relative_to(task_dir)),
            "text": text,
            "truncated": len(text) < original_chars,
            "selection": "ordered_full_context",
        })
        total_chars += len(text)
        if total_chars >= max_context_chars:
            break
    return {
        "task": data,
        "documents": documents,
        "document_count_in_context": len(documents),
        "context_chars": total_chars,
        "activation": {
            "mode": "raw_full",
            "source_document_count": len([p for p in (task_dir / "documents").rglob("*") if p.is_file()]),
            "selected_chunk_count": len(documents),
            "query_terms": [],
        },
    }


def load_activated_context(
    task_dir: Path,
    data: dict[str, Any],
    max_document_chars: int,
    max_context_chars: int,
    max_activated_chunks: int,
    chunk_chars: int,
) -> dict[str, Any]:
    query_terms = context_query_terms(data)
    candidates = []
    source_document_count = 0
    scan_limit = max(max_document_chars, chunk_chars * 8) if max_document_chars > 0 else 0
    for path in sorted((task_dir / "documents").rglob("*")):
        if not path.is_file():
            continue
        source_document_count += 1
        text = read_document(path)
        original_chars = len(text)
        scan_text = text[:scan_limit] if scan_limit > 0 else text
        relative_path = str(path.relative_to(task_dir))
        for chunk_index, (start, end, chunk) in enumerate(chunk_text(scan_text, chunk_chars, overlap_chars=200)):
            score, matched_terms = score_chunk(chunk, relative_path, query_terms, chunk_index)
            if score <= 0 and chunk_index > 0:
                continue
            candidates.append(
                {
                    "filename": path.name,
                    "relative_path": relative_path,
                    "text": chunk,
                    "truncated": end < original_chars,
                    "selection": "activated_evidence_chunk",
                    "chunk_index": chunk_index,
                    "start_char": start,
                    "end_char": end,
                    "score": round(score, 3),
                    "matched_terms": matched_terms,
                }
            )

    candidates.sort(key=lambda item: (-item["score"], item["relative_path"], item["chunk_index"]))
    selected = []
    total_chars = 0
    per_document_counts: dict[str, int] = {}
    max_activated_chunks = max(1, max_activated_chunks)
    for candidate in candidates:
        if len(selected) >= max_activated_chunks or total_chars >= max_context_chars:
            break
        per_doc_limit = 3 if len(per_document_counts) < 6 else 2
        if per_document_counts.get(candidate["relative_path"], 0) >= per_doc_limit:
            continue
        text = candidate["text"]
        if total_chars + len(text) > max_context_chars:
            text = text[: max(0, max_context_chars - total_chars)]
            candidate = {**candidate, "text": text, "truncated": True}
        selected.append(candidate)
        per_document_counts[candidate["relative_path"]] = per_document_counts.get(candidate["relative_path"], 0) + 1
        total_chars += len(text)

    if not selected and candidates:
        first = candidates[0]
        first = {**first, "text": first["text"][:max_context_chars]}
        selected = [first]
        total_chars = len(first["text"])

    selected.sort(key=lambda item: (item["relative_path"], item["chunk_index"]))
    return {
        "task": data,
        "documents": selected,
        "document_count_in_context": len(selected),
        "context_chars": total_chars,
        "activation": {
            "mode": "activated",
            "source_document_count": source_document_count,
            "selected_chunk_count": len(selected),
            "query_terms": query_terms[:40],
            "chunk_chars": chunk_chars,
            "max_activated_chunks": max_activated_chunks,
        },
    }


def load_task_context(
    lab_dir: Path,
    task_id: str,
    max_documents: int,
    max_document_chars: int,
    max_context_chars: int,
    context_mode: str = "activated",
    max_activated_chunks: int = 16,
    chunk_chars: int = 1200,
) -> dict[str, Any]:
    task_dir = lab_dir / "tasks" / task_id
    task_json = task_dir / "task.json"
    data = json.loads(task_json.read_text())
    if context_mode in {"raw_full", "full"}:
        return load_full_context(task_dir, data, max_documents, max_document_chars, max_context_chars)
    if context_mode != "activated":
        raise ValueError(f"unknown context_mode: {context_mode}")
    return load_activated_context(
        task_dir,
        data,
        max_document_chars,
        max_context_chars,
        max_activated_chunks,
        chunk_chars,
    )
