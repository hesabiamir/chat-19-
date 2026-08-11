from __future__ import annotations

import json
import re
from typing import Callable

_DIGIT_TRANSLATION = str.maketrans('۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', '01234567890123456789')


def _normalize(text: str, normalizer: Callable[[str], str] | None = None) -> str:
    value = str(text or '')
    if normalizer is not None:
        return normalizer(value)
    return re.sub(r'[ \t]+', ' ', value.replace('\r\n', '\n').replace('\r', '\n')).strip()


def _canonical_numeric_token(number: str, unit: str) -> str:
    raw_number = number.replace(',', '.')
    try:
        value = float(raw_number)
    except ValueError:
        value = 0.0
    u = re.sub(r'\s+', ' ', unit or '').strip().lower()
    if u in {'kg', 'کیلو', 'کیلوگرم'}:
        canonical_unit = 'کیلوگرم'
    elif u == 'تن':
        value *= 1000.0
        canonical_unit = 'کیلوگرم'
    elif u in {'سانتیمتر', 'سانتی متر'}:
        canonical_unit = 'سانتی متر'
    elif u == 'متر':
        value *= 100.0
        canonical_unit = 'سانتی متر'
    elif u == 'ساعت':
        value *= 60.0
        canonical_unit = 'دقیقه'
    elif u == 'دقیقه':
        canonical_unit = 'دقیقه'
    elif u in {'درصد', '٪'}:
        canonical_unit = 'درصد'
    else:
        canonical_unit = u
    rendered = str(int(round(value))) if abs(value - round(value)) < 1e-9 else (f'{value:.6f}').rstrip('0').rstrip('.')
    return f'{rendered} {canonical_unit}'.strip()


def source_number_unit_tokens(text: str, *, normalizer: Callable[[str], str] | None = None) -> set[str]:
    normalized = _normalize(text, normalizer).translate(_DIGIT_TRANSLATION)
    pattern = r'(?<!\w)(\d+(?:[.,]\d+)?)(?:\s*(کیلوگرم|کیلو|kg|تن|سانتی\s*متر|سانتیمتر|متر|ساعت|دقیقه|درصد|٪|تومان|ریال))?'
    values: set[str] = set()
    for number, unit in re.findall(pattern, normalized, flags=re.I):
        values.add(_canonical_numeric_token(number, unit))
    return values


def text_health_score(text: str) -> float:
    clean = str(text or '')
    if not clean.strip():
        return 0.0
    penalty = 0.0
    penalty += min(0.35, clean.count('[ناخوانا]') * 0.04)
    penalty += min(0.25, clean.count('\ufffd') * 0.08)
    weird = sum(1 for ch in clean if ord(ch) < 32 and ch not in '\n\t\r')
    penalty += min(0.20, weird / max(1, len(clean)) * 20)
    if re.search(r'(.)\1{8,}', clean):
        penalty += 0.12

    # Broken PDF text extraction often looks superficially non-empty while words
    # have been split into one-to-three-character lines/tokens. Penalize only
    # strong fragmentation so legitimate bullets/tables are not rejected.
    lines = [line.strip() for line in clean.splitlines() if line.strip()]
    if len(lines) >= 20:
        short_line_ratio = sum(1 for line in lines if len(line) <= 3) / len(lines)
        if short_line_ratio > 0.22:
            penalty += min(0.30, (short_line_ratio - 0.22) * 0.85)
    persian_tokens = re.findall(r'[آ-ی]+', clean)
    if len(persian_tokens) >= 80:
        one_char_ratio = sum(1 for token in persian_tokens if len(token) == 1) / len(persian_tokens)
        if one_char_ratio > 0.20:
            penalty += min(0.22, (one_char_ratio - 0.20) * 0.80)
    return max(0.0, min(1.0, 1.0 - penalty))


def page_fidelity_metrics(
    base_text: str,
    vision_text: str,
    *,
    vision_full: bool,
    status: str,
    normalizer: Callable[[str], str] | None = None,
) -> tuple[float, float | None]:
    base_health = text_health_score(base_text)
    vision_health = text_health_score(vision_text) if vision_text else (1.0 if status in {'text', 'blank'} else 0.0)
    numeric_agreement: float | None = None
    if vision_full and base_text.strip() and vision_text.strip():
        base_nums = source_number_unit_tokens(base_text, normalizer=normalizer)
        vision_nums = source_number_unit_tokens(vision_text, normalizer=normalizer)
        # Symmetric F1/Jaccard-like agreement: missing numbers and Vision-only
        # numbers are both evidence loss. This prevents a hallucinated extra
        # numeric fact from receiving a perfect fidelity score.
        if not base_nums and not vision_nums:
            numeric_agreement = 1.0
        else:
            intersection = len(base_nums & vision_nums)
            numeric_agreement = (2.0 * intersection) / max(1, len(base_nums) + len(vision_nums))
    if status in {'vision_error', 'vision_skipped', 'vision_unavailable', 'empty'}:
        return 0.25 * base_health, numeric_agreement
    # A scanned/image-only page has no direct-text baseline by definition. A clean
    # full Vision transcription is therefore positive evidence, not a fidelity
    # failure. Numeric cross-checking only applies when both representations exist.
    if vision_full and not base_text.strip() and vision_text.strip():
        score = vision_health * 0.90 + 0.10
    else:
        score = base_health * 0.58 + vision_health * 0.22 + 0.20
        if numeric_agreement is not None:
            score = score * 0.70 + numeric_agreement * 0.30
    return max(0.0, min(1.0, score)), numeric_agreement


def generic_source_quality(
    text: str,
    kind: str,
    *,
    min_extracted_text_chars: int,
    normalizer: Callable[[str], str] | None = None,
) -> tuple[float, list[str]]:
    clean = _normalize(text, normalizer)
    warnings: list[str] = []
    health = text_health_score(clean)
    structural = 1.0
    lines = [x for x in clean.splitlines() if x.strip()]
    if kind == 'csv' and lines:
        counts = [max(line.count(','), line.count(';'), line.count('|')) for line in lines[:300]]
        if max(counts or [0]) == 0:
            structural = 0.72
            warnings.append('CSV ساختار ستونی قابل تشخیص کمی دارد.')
        elif len(set(counts)) > max(5, len(counts) // 3):
            structural = 0.80
            warnings.append('تعداد ستون‌های CSV یکنواخت نیست؛ فایل نیازمند بازبینی است.')
    elif kind == 'xlsx' and '--- شیت:' not in clean:
        structural = 0.72
        warnings.append('ساختار شیت Excel در متن استخراج‌شده تشخیص داده نشد.')
    elif kind == 'docx' and len(lines) < 2:
        structural = 0.82
        warnings.append('سند Word محتوای ساختاری کمی دارد.')
    elif kind == 'json':
        try:
            json.loads(clean)
        except json.JSONDecodeError:
            structural = 0.78
            warnings.append('JSON استخراج‌شده ساختار معتبر JSON ندارد.')
    elif kind in {'html', 'htm'} and len(clean) < min_extracted_text_chars * 2:
        structural = 0.82
        warnings.append('HTML متن قابل جست‌وجوی کمی تولید کرده است.')
    quality = round(max(0.0, min(100.0, (health * 0.68 + structural * 0.32) * 100)), 1)
    return quality, warnings
