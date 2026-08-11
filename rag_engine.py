from __future__ import annotations

import math
import re
import struct
from typing import Any

_PERSIAN_DIGITS = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def pack_vector(values: list[float]) -> bytes:
    if not values:
        return b''
    return struct.pack(f'<{len(values)}f', *[float(v) for v in values])


def unpack_vector(payload: bytes | None) -> list[float]:
    if not payload:
        return []
    if len(payload) % 4:
        return []
    count = len(payload) // 4
    return list(struct.unpack(f'<{count}f', payload))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    aa = sum(x * x for x in a)
    bb = sum(y * y for y in b)
    if aa <= 0.0 or bb <= 0.0:
        return 0.0
    return max(-1.0, min(1.0, dot / math.sqrt(aa * bb)))


def normalize_digits(text: str) -> str:
    return str(text or '').translate(_PERSIAN_DIGITS)


def numeric_tokens(text: str) -> set[str]:
    text = normalize_digits(text)
    return set(re.findall(r'(?<!\w)\d+(?:[.,]\d+)?(?!\w)', text))


def extract_structured_facts(text: str, *, page_start: int | None, page_end: int | None, section_title: str | None) -> list[dict[str, Any]]:
    """Conservative deterministic extraction for numeric/conditional policy facts.

    It intentionally stores only lines that already exist in the source. It does not
    invent normalized values; the raw source sentence remains the authoritative fact.
    """
    raw = str(text or '').strip()
    if not raw:
        return []
    lines = [re.sub(r'\s+', ' ', line).strip(' -–—•\t') for line in re.split(r'[\n\r]+', raw)]
    lines = [line for line in lines if 8 <= len(line) <= 700]
    unit_pattern = r'(?:کیلوگرم|کیلو|kg|تن|تومان|ریال|درصد|٪|روز|ماه|سال|ساعت|دقیقه|متر|سانتی(?:متر)?|عدد|دستگاه)'
    condition_markers = ('اگر', 'در صورتی', 'در شرایط', 'به شرط', 'استثنا', 'تبصره', 'مگر', 'فقط در', 'حداکثر', 'حداقل', 'بالاتر', 'پایین‌تر', 'محدوده', 'منطقه')
    subject_markers = ('نیسان', 'پیکان', 'خاور', 'اریسان', 'وانت', 'بار', 'روبار', 'روباری', 'باربند', 'سرویس', 'راننده', 'مشتری')
    facts: list[dict[str, Any]] = []
    for line in lines:
        normalized = normalize_digits(line)
        numbers = re.findall(r'(?<!\w)\d+(?:[.,]\d+)?(?!\w)', normalized)
        has_unit = bool(re.search(unit_pattern, line, flags=re.I))
        has_condition = any(marker in line for marker in condition_markers)
        if not numbers and not has_condition:
            continue
        if numbers and not (has_unit or has_condition or any(marker in line for marker in subject_markers)):
            continue
        subject = next((marker for marker in subject_markers if marker in line), '')
        condition = ''
        if has_condition:
            parts = re.split(r'(?=اگر|در صورتی|در شرایط|به شرط|استثنا|تبصره|مگر|فقط در)', line, maxsplit=1)
            condition = parts[-1] if len(parts) > 1 else line
        facts.append({
            'subject': subject,
            'fact_type': 'conditional' if has_condition else 'numeric' if numbers else 'rule',
            'value_text': '، '.join(numbers[:8]),
            'condition_text': condition[:500],
            'fact_text': line[:900],
            'page_start': page_start,
            'page_end': page_end,
            'section_title': section_title or '',
        })
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for fact in facts:
        key = fact['fact_text']
        if key in seen:
            continue
        seen.add(key)
        output.append(fact)
    return output[:80]


def rerank_hybrid_candidates(question: str, candidates: list[dict[str, Any]], *, top_n: int = 32) -> list[dict[str, Any]]:
    """Second-stage deterministic reranker.

    First-stage retrieval can come from FTS, local semantic buckets, facts, or remote
    embeddings. This stage gives extra weight to candidates supported by multiple
    independent signals and to candidates that preserve numeric/conditional context.
    """
    qnums = numeric_tokens(question)
    ranked: list[dict[str, Any]] = []
    for raw in candidates:
        item = dict(raw)
        lexical = float(item.get('lexical_score') or 0.0)
        local_semantic = float(item.get('semantic_score') or 0.0)
        embedding = float(item.get('embedding_score') or 0.0)
        numeric = float(item.get('numeric_score') or 0.0)
        fact = float(item.get('fact_score') or 0.0)
        bucket_hits = int(item.get('bucket_hits') or 0)
        content = str(item.get('content') or '')
        cnums = numeric_tokens(content)
        exact_number = 1.0 if qnums and qnums.issubset(cnums) else 0.0
        conditional = 1.0 if any(x in content for x in ('تبصره', 'استثنا', 'در شرایط', 'در صورتی', 'اگر', 'حداکثر', 'حداقل')) else 0.0
        signal_count = sum(score >= 0.18 for score in (lexical, local_semantic, embedding, fact))
        consensus = min(0.16, signal_count * 0.04 + min(0.05, bucket_hits * 0.006))
        score = (
            lexical * 0.42
            + local_semantic * 0.20
            + embedding * 0.62
            + numeric * 0.13
            + fact * 0.22
            + exact_number * 0.07
            + conditional * 0.025
            + consensus
        )
        item['rerank_score'] = round(score, 5)
        item['score'] = round(max(float(item.get('score') or 0.0), score), 5)
        ranked.append(item)
    ranked.sort(key=lambda x: (-float(x.get('rerank_score') or 0.0), float(x.get('rank') or 0.0), str(x.get('document_id') or ''), int(x.get('chunk_index') or 0)))
    return ranked[:max(1, top_n)]
