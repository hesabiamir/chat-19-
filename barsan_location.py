from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


IRAN_CENTER_LATITUDE = 32.4279
IRAN_CENTER_LONGITUDE = 53.6880
_PERSIAN_TRANSLATION = str.maketrans(
    {
        "ي": "ی",
        "ى": "ی",
        "ك": "ک",
        "ة": "ه",
        "ۀ": "ه",
        "۰": "0",
        "۱": "1",
        "۲": "2",
        "۳": "3",
        "۴": "4",
        "۵": "5",
        "۶": "6",
        "۷": "7",
        "۸": "8",
        "۹": "9",
    }
)
_ADDRESS_MARKERS = {
    "آدرس",
    "ادرس",
    "خیابان",
    "خ",
    "بلوار",
    "کوچه",
    "میدان",
    "محله",
    "شهرک",
    "روستا",
    "جاده",
    "بزرگراه",
    "اتوبان",
    "پلاک",
    "کارخانه",
    "فروشگاه",
    "مغازه",
    "شرکت",
    "دفتر",
    "انبار",
    "مجتمع",
}
_EXPLICIT_LOCATION_MARKERS = {
    "مسیریابی",
    "لوکیشن",
    "موقعیت",
    "روی نقشه",
    "لینک نقشه",
    "کجاست",
    "پیدا کن",
    "پیداش کن",
    "آدرسش",
    "ادرسش",
}
_POI_MARKERS = {
    "کارخانه",
    "فروشگاه",
    "مغازه",
    "شرکت",
    "دفتر",
    "انبار",
    "رستوران",
    "بیمارستان",
    "داروخانه",
    "مدرسه",
    "دانشگاه",
    "بانک",
    "پمپ بنزین",
    "مجتمع",
    "پاساژ",
}
_COMMAND_PREFIX = re.compile(
    r"^(?:لطفا|لطفاً|خواهشاً)?\s*(?:مسیریابی|لوکیشن|موقعیت|آدرس|ادرس|مکان)\s*"
    r"(?:را|رو|این|برای|یعنی|:|：|-)?\s*",
    flags=re.IGNORECASE,
)


class NeshanServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class MapirServiceError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class LocationLookup:
    query: str
    normalized_query: str
    items: list[dict[str, Any]]
    provider_calls: int
    used_plus: bool
    used_search: bool


def normalize_location_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_PERSIAN_TRANSLATION)
    text = re.sub(r"[\u200b-\u200f\u202a-\u202e\u2066-\u2069\ufeff]", "", text)
    text = re.sub(r"[،,؛;|]+", " ", text)
    text = re.sub(r"\bخ\.?\s+", "خیابان ", text)
    text = re.sub(r"\bب\.?\s+", "بلوار ", text)
    text = re.sub(r"\bک\.?\s+", "کوچه ", text)
    # Common speech-to-text spellings for the well-known Ahmadabad Mostofi area.
    text = re.sub(r"\bاحمد[اآ]باد\b", "احمدآباد", text)
    text = re.sub(r"\bموستقی\b", "مستوفی", text)
    return re.sub(r"\s+", " ", text).strip(" .،؛:!?؟-")


def is_location_request(message: str) -> bool:
    normalized = normalize_location_text(message).lower()
    if not normalized or len(normalized) < 4:
        return False
    if any(marker in normalized for marker in _EXPLICIT_LOCATION_MARKERS):
        return True
    tokens = set(normalized.split())
    marker_hits = tokens & _ADDRESS_MARKERS
    return bool(marker_hits and len(tokens) >= 3)


def extract_location_query(message: str) -> str:
    text = normalize_location_text(message)
    text = _COMMAND_PREFIX.sub("", text)
    text = re.sub(
        r"(?:را|رو)?\s*(?:روی نقشه|در نشان|با نشان)?\s*(?:پیدا کن|پیداش کن|نشان بده|بفرست|ارسال کن)\s*$",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return normalize_location_text(text)


def query_needs_poi_search(query: str) -> bool:
    normalized = normalize_location_text(query)
    return any(marker in normalized for marker in _POI_MARKERS)


def _location_from_item(item: dict[str, Any]) -> tuple[float, float] | None:
    raw = item.get("location") or {}
    try:
        latitude = float(raw.get("latitude", raw.get("y")))
        longitude = float(raw.get("longitude", raw.get("x")))
    except (TypeError, ValueError):
        return None
    if not (24.0 <= latitude <= 40.5 and 43.0 <= longitude <= 64.5):
        return None
    return latitude, longitude


def _map_links(latitude: float, longitude: float) -> tuple[str, str]:
    map_url = f"https://maps.neshan.org/@{latitude:.6f},{longitude:.6f},16.0z,0.0p"
    navigation_url = f"https://nshn.ir/?lat={latitude:.6f}&lng={longitude:.6f}"
    return map_url, navigation_url


def public_map_links(latitude: float, longitude: float) -> dict[str, str]:
    """Return provider-independent links so a result is usable in any common map."""
    return {
        "map_url": f"https://maps.neshan.org/@{latitude:.6f},{longitude:.6f},16.0z,0.0p",
        "navigation_url": f"https://nshn.ir/?lat={latitude:.6f}&lng={longitude:.6f}",
        "google_maps_url": f"https://www.google.com/maps/search/?api=1&query={latitude:.6f},{longitude:.6f}",
        "balad_url": f"https://balad.ir/location?latitude={latitude:.6f}&longitude={longitude:.6f}&zoom=16",
    }


def _tokens(value: str) -> set[str]:
    return {token for token in normalize_location_text(value).lower().split() if len(token) >= 2}


def _query_match_score(query: str, *values: str) -> float:
    query_tokens = _tokens(query)
    candidate_tokens = _tokens(" ".join(values))
    if not query_tokens or not candidate_tokens:
        return 0.0
    containment = len(query_tokens & candidate_tokens) / len(query_tokens)
    jaccard = len(query_tokens & candidate_tokens) / len(query_tokens | candidate_tokens)
    return min(1.0, containment * 0.72 + jaccard * 0.28)


def normalize_geocoding_items(query: str, payload: Any) -> list[dict[str, Any]]:
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    results: list[dict[str, Any]] = []
    query_length = max(1, len(normalize_location_text(query).replace(" ", "")))
    for index, raw in enumerate(raw_items[:10]):
        if not isinstance(raw, dict):
            continue
        point = _location_from_item(raw)
        if point is None:
            continue
        latitude, longitude = point
        province = str(raw.get("province") or "").strip()
        city = str(raw.get("city") or "").strip()
        neighbourhood = str(raw.get("neighbourhood") or "").strip()
        unmatched = str(raw.get("unMatchedTerm") or raw.get("unmatchedTerm") or "").strip()
        unmatched_ratio = min(1.0, len(normalize_location_text(unmatched).replace(" ", "")) / query_length)
        confidence = max(0.25, min(0.99, 0.98 - index * 0.035 - unmatched_ratio * 0.62))
        title = "، ".join(part for part in (neighbourhood, city) if part) or query
        resolved_address = "، ".join(part for part in (province, city, neighbourhood) if part) or query
        map_url, navigation_url = _map_links(latitude, longitude)
        results.append(
            {
                "title": title,
                "address": resolved_address,
                "province": province,
                "city": city,
                "neighbourhood": neighbourhood,
                "unmatched_term": unmatched,
                "latitude": latitude,
                "longitude": longitude,
                "confidence": round(confidence, 4),
                "provider": "neshan_geocoding",
                "map_url": map_url,
                "navigation_url": navigation_url,
            }
        )
    return results


def normalize_search_items(query: str, payload: Any) -> list[dict[str, Any]]:
    raw_items = payload.get("items", []) if isinstance(payload, dict) else []
    results: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items[:30]):
        if not isinstance(raw, dict):
            continue
        point = _location_from_item(raw)
        if point is None:
            continue
        latitude, longitude = point
        title = str(raw.get("title") or "").strip()
        address = str(raw.get("address") or "").strip()
        region = str(raw.get("region") or "").strip()
        neighbourhood = str(raw.get("neighbourhood") or "").strip()
        text_score = _query_match_score(query, title, address, region, neighbourhood)
        confidence = max(0.2, min(0.995, 0.45 + text_score * 0.52 - index * 0.006))
        map_url, navigation_url = _map_links(latitude, longitude)
        results.append(
            {
                "title": title or query,
                "address": "، ".join(part for part in (address, region) if part) or query,
                "province": "",
                "city": region.split("،")[0].strip() if region else "",
                "neighbourhood": neighbourhood,
                "unmatched_term": "",
                "latitude": latitude,
                "longitude": longitude,
                "confidence": round(confidence, 4),
                "provider": "neshan_search",
                "map_url": map_url,
                "navigation_url": navigation_url,
                "category": str(raw.get("category") or ""),
                "type": str(raw.get("type") or ""),
            }
        )
    return results


def normalize_mapir_items(query: str, payload: Any) -> list[dict[str, Any]]:
    raw_items = payload if isinstance(payload, list) else (payload.get("items", []) if isinstance(payload, dict) else [])
    results: list[dict[str, Any]] = []
    for index, raw in enumerate(raw_items[:30]):
        if not isinstance(raw, dict):
            continue
        coordinate = raw.get("Coordinate") or raw.get("coordinate") or {}
        try:
            latitude = float(coordinate.get("lat"))
            longitude = float(coordinate.get("lon"))
        except (TypeError, ValueError):
            continue
        if not (24.0 <= latitude <= 40.5 and 43.0 <= longitude <= 64.5):
            continue
        title = str(raw.get("Title") or raw.get("Text") or query).strip()
        address = str(raw.get("Address") or raw.get("Text") or title).strip()
        province = str(raw.get("Province") or "").strip()
        city = str(raw.get("City") or "").strip()
        text_score = _query_match_score(query, title, address, province, city)
        confidence = max(0.2, min(0.995, 0.43 + text_score * 0.54 - index * 0.007))
        results.append(
            {
                "title": title,
                "address": address,
                "province": province,
                "city": city,
                "neighbourhood": "",
                "unmatched_term": "",
                "latitude": latitude,
                "longitude": longitude,
                "confidence": round(confidence, 4),
                "provider": "mapir_search",
                "category": str(raw.get("Type") or raw.get("FClass") or ""),
                **public_map_links(latitude, longitude),
            }
        )
    return results


async def lookup_mapir(
    client: Any,
    *,
    api_key: str,
    query: str,
    search_url: str = "https://map.ir/search",
    timeout_seconds: float = 10.0,
    max_results: int = 5,
    reference_latitude: float = 35.6997,
    reference_longitude: float = 51.3379,
) -> LocationLookup:
    normalized_query = extract_location_query(query)
    if len(normalized_query) < 3:
        raise ValueError("آدرس برای جست‌وجو بیش از حد کوتاه است.")
    if not api_key:
        raise MapirServiceError("کلید API نقشه Map.ir تنظیم نشده است.")
    payload = {
        "text": normalized_query,
        "location": {
            "type": "Point",
            "coordinates": [float(reference_longitude), float(reference_latitude)],
        },
    }
    try:
        response = await client.post(
            search_url,
            json=payload,
            headers={"x-api-key": api_key, "Accept": "application/json", "Content-Type": "application/json"},
            timeout=timeout_seconds,
        )
    except Exception as exc:
        raise MapirServiceError("ارتباط با سرویس Map.ir برقرار نشد.") from exc
    if response.status_code >= 400:
        raise MapirServiceError(f"سرویس Map.ir HTTP {response.status_code}", int(response.status_code))
    try:
        items = normalize_mapir_items(normalized_query, response.json())
    except Exception as exc:
        raise MapirServiceError("پاسخ سرویس Map.ir قابل پردازش نبود.") from exc
    items = merge_location_items(normalized_query, items, limit=max_results)
    return LocationLookup(
        query=query,
        normalized_query=normalized_query,
        items=items,
        provider_calls=1,
        used_plus=False,
        used_search=True,
    )


def _distance_meters(a: dict[str, Any], b: dict[str, Any]) -> float:
    lat1, lon1 = math.radians(float(a["latitude"])), math.radians(float(a["longitude"]))
    lat2, lon2 = math.radians(float(b["latitude"])), math.radians(float(b["longitude"]))
    dlat, dlon = lat2 - lat1, lon2 - lon1
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6_371_000 * 2 * math.atan2(math.sqrt(value), math.sqrt(max(0.0, 1 - value)))


def merge_location_items(query: str, *groups: list[dict[str, Any]], limit: int = 5) -> list[dict[str, Any]]:
    candidates = [dict(item) for group in groups for item in group]
    for item in candidates:
        item.update({key: value for key, value in public_map_links(float(item["latitude"]), float(item["longitude"])).items() if not item.get(key)})
        text_score = _query_match_score(query, str(item.get("title") or ""), str(item.get("address") or ""))
        provider_bonus = 0.08 if item.get("provider") == "neshan_search" and text_score >= 0.45 else 0.0
        item["confidence"] = round(min(0.995, float(item.get("confidence") or 0.0) * 0.78 + text_score * 0.22 + provider_bonus), 4)
    candidates.sort(key=lambda item: float(item.get("confidence") or 0.0), reverse=True)
    unique: list[dict[str, Any]] = []
    for candidate in candidates:
        if any(_distance_meters(candidate, existing) < 25 for existing in unique):
            continue
        unique.append(candidate)
        if len(unique) >= max(1, limit):
            break
    return unique


async def lookup_neshan(
    client: Any,
    *,
    api_key: str,
    query: str,
    city: str = "",
    province: str = "",
    geocoding_url: str = "https://api.neshan.org/geocoding/v1",
    search_url: str = "https://api.neshan.org/v3/search",
    use_plus: bool = True,
    search_enrichment: bool = True,
    timeout_seconds: float = 10.0,
    max_results: int = 5,
) -> LocationLookup:
    normalized_query = extract_location_query(query)
    if len(normalized_query) < 3:
        raise ValueError("آدرس برای جست‌وجو بیش از حد کوتاه است.")
    if not api_key:
        raise NeshanServiceError("کلید API نشان تنظیم نشده است.")
    headers = {"Api-Key": api_key, "Accept": "application/json", "Content-Type": "application/json"}
    request_data: dict[str, Any] = {"address": normalized_query}
    if city.strip():
        request_data["city"] = normalize_location_text(city)
    if province.strip():
        request_data["province"] = normalize_location_text(province)
    provider_calls = 0
    geocoding_items: list[dict[str, Any]] = []
    used_plus = False
    endpoints = [f"{geocoding_url.rstrip('/')}/plus", geocoding_url.rstrip("/")] if use_plus else [geocoding_url.rstrip("/")]
    last_status: int | None = None
    last_error = ""
    for endpoint in endpoints:
        try:
            provider_calls += 1
            response = await client.get(
                endpoint,
                params={"json": json.dumps(request_data, ensure_ascii=False, separators=(",", ":"))},
                headers=headers,
                timeout=timeout_seconds,
            )
            last_status = int(response.status_code)
            if response.status_code >= 400:
                last_error = str(getattr(response, "text", ""))[:240]
                if endpoint.endswith("/plus") and response.status_code in {400, 403, 480, 481, 482, 483, 484, 485}:
                    continue
                raise NeshanServiceError(f"سرویس نشان HTTP {response.status_code}", response.status_code)
            geocoding_items = normalize_geocoding_items(normalized_query, response.json())
            used_plus = endpoint.endswith("/plus")
            break
        except NeshanServiceError:
            raise
        except Exception as exc:
            last_error = str(exc)[:240]
            if endpoint.endswith("/plus"):
                continue
            raise NeshanServiceError("ارتباط با سرویس نشان برقرار نشد.") from exc
    if not geocoding_items and last_status and last_status >= 400:
        raise NeshanServiceError(f"سرویس نشان نتیجه نداد: HTTP {last_status} {last_error}".strip(), last_status)

    search_items: list[dict[str, Any]] = []
    should_search = bool(geocoding_items and search_enrichment and query_needs_poi_search(normalized_query))
    if should_search:
        center = geocoding_items[0]
        search_query = {
            "term": normalized_query,
            "center": {"latitude": center["latitude"], "longitude": center["longitude"]},
        }
        try:
            provider_calls += 1
            response = await client.get(
                search_url,
                params={"q": json.dumps(search_query, ensure_ascii=False, separators=(",", ":"))},
                headers=headers,
                timeout=timeout_seconds,
            )
            if response.status_code < 400:
                search_items = normalize_search_items(normalized_query, response.json())
        except Exception:
            # Geocoding remains usable even when Search v3 is not enabled for a key.
            search_items = []
    items = merge_location_items(normalized_query, search_items, geocoding_items, limit=max_results)
    return LocationLookup(
        query=query,
        normalized_query=normalized_query,
        items=items,
        provider_calls=provider_calls,
        used_plus=used_plus,
        used_search=bool(search_items),
    )


def format_location_answer(query: str, items: list[dict[str, Any]]) -> str:
    if not items:
        return "برای این آدرس موقعیت قابل اتکایی در نشان پیدا نشد. نام استان، شهر یا یک نشانه نزدیک را هم اضافه کنید."
    best = items[0]
    confidence = int(round(float(best.get("confidence") or 0.0) * 100))
    lines = [
        f"دقیق‌ترین موقعیت پیدا‌شده برای «{query}»: {best.get('title') or query}",
        f"آدرس تطبیق‌یافته: {best.get('address') or '—'}",
        f"مختصات: {float(best['latitude']):.6f}, {float(best['longitude']):.6f}",
        f"اطمینان تطبیق: {confidence}٪",
        f"لینک نشان: {best.get('map_url')}",
        f"لینک ارسال به مسیریاب: {best.get('navigation_url')}",
        f"لینک Google Maps: {best.get('google_maps_url')}",
        f"لینک بلد: {best.get('balad_url')}",
    ]
    unmatched = str(best.get("unmatched_term") or "").strip()
    if unmatched:
        lines.append(f"بخش تطبیق‌نیافته آدرس: {unmatched}")
    if len(items) > 1:
        lines.append(f"{len(items) - 1} پیشنهاد جایگزین هم در کارت‌های پایین نمایش داده شده است.")
    return "\n".join(lines)
