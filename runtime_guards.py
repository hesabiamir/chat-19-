from __future__ import annotations

from typing import Any, Iterable

DOCUMENT_SOURCE_TYPES = {"document", "resource", "pdf", "google_doc"}


def document_source_ids(sources: Iterable[dict[str, Any]] | None) -> list[str]:
    """Return unique document ids referenced by an answer/cache payload."""
    result: list[str] = []
    seen: set[str] = set()
    for item in sources or []:
        source_type = str(item.get("source_type") or "").strip().lower()
        if source_type not in DOCUMENT_SOURCE_TYPES:
            continue
        document_id = str(item.get("document_id") or "").strip()
        if document_id and document_id not in seen:
            seen.add(document_id)
            result.append(document_id)
    return result


def preserve_live_document_status(current_status: str | None, chunk_count: int | None) -> str:
    """Keep the last known-good index visible while a staging reindex retries/fails."""
    status = str(current_status or "").strip().lower()
    if status == "ready" and int(chunk_count or 0) > 0:
        return "ready"
    if int(chunk_count or 0) > 0 and status not in {"missing", "disabled"}:
        return status or "partial"
    return "processing"


def document_job_priority(job_type: str | None, phase: str | None = None) -> int:
    """Stable priority: fresh uploads > page repair > manual reindex > background migration."""
    jt = str(job_type or "").strip().lower()
    ph = str(phase or "").strip().lower()
    if jt in {"ingest", "upload", "google_doc"}:
        return 100
    if jt in {"retry_pages", "page_repair"}:
        return 90
    if "دستی" in ph or "manual" in ph:
        return 75
    if "مهاجرت" in ph or "غنی" in ph or jt in {"migration", "background"}:
        return 20
    if jt == "reindex":
        return 60
    return 50
