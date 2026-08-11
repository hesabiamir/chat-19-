from __future__ import annotations

import itertools
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


def normalize_cargo_text(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).translate(_DIGITS)
    text = text.translate(str.maketrans({"ي": "ی", "ك": "ک"}))
    return re.sub(r"\s+", " ", text).strip()


def is_cargo_request(value: str) -> bool:
    text = normalize_cargo_text(value).lower()
    explicit = (
        "بررسی بار", "جا میشه", "جا می‌شود", "جا میشود", "جا نمیشه", "جا نمی‌شود",
        "بیرون میزنه", "بیرون می‌زنه", "ارتفاع میگیره", "ارتفاع می‌گیره", "چقدر ارتفاع",
    )
    if any(x in text for x in explicit):
        return True
    tokens = set(re.findall(r"[\w‌]+", text, flags=re.UNICODE))
    vehicle = {"ماشین", "خودرو", "پیکان", "نیسان", "وانت", "خاور", "اریسان", "کامیون"}
    load = {"بار", "جعبه", "کارتن", "لوله", "سینی", "کابل", "وال", "پست", "پروفیل", "ورق", "پالت", "بسته", "کالا"}
    measurement = {"ابعاد", "ارتفاع", "عرض", "طول", "وزن", "کیلو", "کیلوگرم", "متر", "سانت", "تعداد"}
    return bool(tokens & vehicle) and bool(tokens & load) and (bool(tokens & measurement) or bool(re.search(r"\d", text)))


@dataclass(frozen=True)
class CargoItem:
    name: str
    count: int
    length_cm: float
    width_cm: float
    height_cm: float
    weight_kg: float | None = None
    rotatable: bool = True


def _orientations(length: float, width: float, height: float, rotatable: bool = True) -> list[tuple[float, float, float]]:
    base = (float(length), float(width), float(height))
    return sorted(set(itertools.permutations(base))) if rotatable else [base]


def _layout_for_orientation(vehicle: tuple[float, float, float], item: CargoItem, orientation: tuple[float, float, float]) -> dict[str, Any]:
    """Find a practical rectangular packing layout for identical boxes.

    The optimizer tests every possible number of vertical layers. It strongly avoids
    side overflow, then rear overflow, then height overflow. This makes the reported
    "از در عقب بیرون می‌زند" and total stack height useful for operators instead of
    merely comparing one box with the vehicle envelope.
    """
    vl, vw, vh = map(float, vehicle)
    a, b, c = orientation
    best: dict[str, Any] | None = None
    max_layers = max(1, item.count)
    for layers in range(1, max_layers + 1):
        per_layer = math.ceil(item.count / layers)
        max_cols_inside = max(1, math.floor(vw / b)) if b > 0 else 1
        # Try every useful column count; more columns can reduce rear overhang while
        # fewer columns can reduce side overflow for oversized pieces.
        for cols in range(1, min(per_layer, max_cols_inside + 2) + 1):
            rows = math.ceil(per_layer / cols)
            occupied_length = rows * a
            occupied_width = min(cols, per_layer) * b
            occupied_height = layers * c
            rear = max(0.0, occupied_length - vl)
            side = max(0.0, occupied_width - vw)
            height_over = max(0.0, occupied_height - vh)
            footprint_area = occupied_length * occupied_width
            # Safety/order preference: width overflow is worst, then rear, then height.
            score = (
                1 if side > 1e-9 else 0,
                round(side, 6),
                1 if rear > 1e-9 else 0,
                round(rear, 6),
                1 if height_over > 1e-9 else 0,
                round(height_over, 6),
                round(occupied_height, 6),
                round(footprint_area, 6),
                layers,
            )
            candidate = {
                "orientation": orientation,
                "rows": rows,
                "columns": cols,
                "layers": layers,
                "occupied_length_cm": occupied_length,
                "occupied_width_cm": occupied_width,
                "occupied_height_cm": occupied_height,
                "rear_overhang_cm": rear,
                "side_overhang_cm": side,
                "height_overflow_cm": height_over,
                "score": score,
            }
            if best is None or score < best["score"]:
                best = candidate
    assert best is not None
    return best


def best_box_layout(vehicle: tuple[float, float, float], item: CargoItem) -> dict[str, Any]:
    candidates = [_layout_for_orientation(vehicle, item, o) for o in _orientations(item.length_cm, item.width_cm, item.height_cm, item.rotatable)]
    return min(candidates, key=lambda x: x["score"])


def box_capacity(vehicle: tuple[float, float, float], item: CargoItem) -> dict[str, Any]:
    best_count = 0
    best_orientation = (item.length_cm, item.width_cm, item.height_cm)
    best_grid = (0, 0, 0)
    for a, b, c in _orientations(item.length_cm, item.width_cm, item.height_cm, item.rotatable):
        grid = (math.floor(vehicle[0] / a), math.floor(vehicle[1] / b), math.floor(vehicle[2] / c))
        capacity = max(0, grid[0]) * max(0, grid[1]) * max(0, grid[2])
        if capacity > best_count:
            best_count, best_orientation, best_grid = capacity, (a, b, c), grid
    return {"capacity": best_count, "orientation": best_orientation, "grid": best_grid}


def calculate_cargo_fit(vehicle: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    vl = float(vehicle["length_cm"])
    vw = float(vehicle["width_cm"])
    vh = float(vehicle["height_cm"])
    if min(vl, vw, vh) <= 0:
        raise ValueError("ابعاد خودرو باید بزرگ‌تر از صفر باشد.")
    vehicle_volume = vl * vw * vh
    max_weight = float(vehicle["max_weight_kg"]) if vehicle.get("max_weight_kg") not in (None, "") else None
    total_volume = 0.0
    total_weight = 0.0
    has_all_weights = True
    results: list[dict[str, Any]] = []
    rear_overhang = side_overhang = height_overflow = 0.0
    max_stack_height = 0.0
    dimension_fit = True

    for raw in items:
        item = CargoItem(
            name=str(raw.get("name") or "بار").strip()[:100],
            count=max(1, int(raw.get("count") or 1)),
            length_cm=float(raw["length_cm"]),
            width_cm=float(raw["width_cm"]),
            height_cm=float(raw["height_cm"]),
            weight_kg=float(raw["weight_kg"]) if raw.get("weight_kg") not in (None, "") else None,
            rotatable=bool(raw.get("rotatable", True)),
        )
        if min(item.length_cm, item.width_cm, item.height_cm) <= 0:
            raise ValueError(f"ابعاد «{item.name}» باید بزرگ‌تر از صفر باشد.")

        capacity = box_capacity((vl, vw, vh), item)
        layout = best_box_layout((vl, vw, vh), item)
        fits_by_layout = (
            layout["rear_overhang_cm"] <= 1e-9
            and layout["side_overhang_cm"] <= 1e-9
            and layout["height_overflow_cm"] <= 1e-9
        )
        item_volume = item.length_cm * item.width_cm * item.height_cm * item.count
        total_volume += item_volume
        if item.weight_kg is None:
            has_all_weights = False
        else:
            total_weight += item.weight_kg * item.count

        rear_overhang = max(rear_overhang, float(layout["rear_overhang_cm"]))
        side_overhang = max(side_overhang, float(layout["side_overhang_cm"]))
        height_overflow = max(height_overflow, float(layout["height_overflow_cm"]))
        max_stack_height = max(max_stack_height, float(layout["occupied_height_cm"]))
        if not fits_by_layout:
            dimension_fit = False

        loadable_count = min(item.count, int(capacity["capacity"]))
        unloadable_count = max(0, item.count - loadable_count)
        results.append(
            {
                "name": item.name,
                "requested_count": item.count,
                "capacity": int(capacity["capacity"]),
                "loadable_count": loadable_count,
                "unloadable_count": unloadable_count,
                "fits": fits_by_layout and unloadable_count == 0,
                "orientation": [round(x, 2) for x in layout["orientation"]],
                "grid": [int(layout["rows"]), int(layout["columns"]), int(layout["layers"])],
                "rows": int(layout["rows"]),
                "columns": int(layout["columns"]),
                "layers": int(layout["layers"]),
                "occupied_length_cm": round(float(layout["occupied_length_cm"]), 2),
                "occupied_width_cm": round(float(layout["occupied_width_cm"]), 2),
                "occupied_height_cm": round(float(layout["occupied_height_cm"]), 2),
                "rear_overhang_cm": round(float(layout["rear_overhang_cm"]), 2),
                "side_overhang_cm": round(float(layout["side_overhang_cm"]), 2),
                "height_overflow_cm": round(float(layout["height_overflow_cm"]), 2),
            }
        )

    volume_fit = total_volume <= vehicle_volume + 1e-6
    weight_fit = None if max_weight is None or not has_all_weights else total_weight <= max_weight
    total_requested_count = sum(int(x.get("requested_count") or 0) for x in results)
    total_loadable_count = sum(int(x.get("loadable_count") or 0) for x in results)
    total_unloadable_count = sum(int(x.get("unloadable_count") or 0) for x in results)
    fits = dimension_fit and volume_fit and weight_fit is not False and total_unloadable_count == 0
    warnings: list[str] = []
    if len(items) > 1:
        warnings.append("در بار ترکیبی، چیدمان دقیق می‌تواند به شکل واقعی قطعات و امکان قرارگیری کنار هم وابسته باشد؛ هر قلم جداگانه و حجم/وزن کل کنترل شده است.")
    if max_weight is not None and not has_all_weights:
        warnings.append("وزن همه اقلام وارد نشده است؛ نتیجه وزنی قطعی نیست و فقط ابعاد/حجم بررسی شده است.")
    if side_overhang > 0:
        warnings.append("بار از عرض مفید خودرو بیرون می‌زند؛ این حالت نیازمند بررسی ایمنی و مقررات است.")
    if height_overflow > 0:
        warnings.append("ارتفاع چیدمان از ارتفاع مفید ثبت‌شده خودرو بیشتر است.")
    return {
        "fits": fits,
        "dimension_fit": dimension_fit,
        "volume_fit": volume_fit,
        "weight_fit": weight_fit,
        "vehicle": {
            "name": str(vehicle.get("name") or "خودرو"),
            "length_cm": round(vl, 2),
            "width_cm": round(vw, 2),
            "height_cm": round(vh, 2),
            "max_weight_kg": round(max_weight, 2) if max_weight is not None else None,
        },
        "vehicle_volume_cm3": round(vehicle_volume, 2),
        "cargo_volume_cm3": round(total_volume, 2),
        "volume_utilization_percent": round(total_volume / vehicle_volume * 100, 2),
        "total_weight_kg": round(total_weight, 2) if has_all_weights else None,
        "rear_overhang_cm": round(rear_overhang, 2),
        "side_overhang_cm": round(side_overhang, 2),
        "occupied_height_cm": round(max_stack_height, 2),
        "height_overflow_cm": round(height_overflow, 2),
        "total_requested_count": total_requested_count,
        "total_loadable_count": total_loadable_count,
        "total_unloadable_count": total_unloadable_count,
        "items": results,
        "warnings": warnings,
    }


def format_cargo_result(result: dict[str, Any]) -> str:
    status = "بار با اطلاعات واردشده داخل خودرو جا می‌شود." if result["fits"] else "بار با چیدمان محاسبه‌شده به‌طور کامل داخل محدوده مفید خودرو جا نمی‌شود."
    lines = [status]
    vehicle = result.get("vehicle") or {}
    lines.append(
        f"فضای مفید {vehicle.get('name','خودرو')}: {vehicle.get('length_cm')}×{vehicle.get('width_cm')}×{vehicle.get('height_cm')} سانتی‌متر."
    )
    for item in result["items"]:
        rows, cols, layers = item["grid"]
        lines.append(
            f"{item['name']}: درخواست {item['requested_count']} عدد؛ داخل ابعاد مفید حداکثر {item.get('loadable_count', item.get('capacity', 0))} عدد جا می‌شود"
            f" و {item.get('unloadable_count', 0)} عدد قابل بارگیری داخل محدوده نیست؛ چیدمان پیشنهادی {rows} ردیف × {cols} ستون × {layers} لایه؛ "
            f"ارتفاع نهایی برای کل تعداد واردشده {item['occupied_height_cm']} سانتی‌متر."
        )
        if item["rear_overhang_cm"] > 0:
            lines.append(f"بیرون‌زدگی تقریبی از انتهای فضای مفید برای {item['name']}: {item['rear_overhang_cm']} سانتی‌متر.")
        if item["side_overhang_cm"] > 0:
            lines.append(f"بیرون‌زدگی از عرض برای {item['name']}: {item['side_overhang_cm']} سانتی‌متر.")
        if item["height_overflow_cm"] > 0:
            lines.append(f"مازاد ارتفاع برای {item['name']}: {item['height_overflow_cm']} سانتی‌متر.")
    lines.append(f"اشغال حجمی تقریبی: {result['volume_utilization_percent']}٪.")
    if result.get("total_weight_kg") is not None:
        lines.append(f"وزن کل واردشده: {result['total_weight_kg']} کیلوگرم.")
    if result.get("weight_fit") is False:
        lines.append("وزن بار از ظرفیت وزنی ثبت‌شده خودرو بیشتر است.")
    lines.extend(result.get("warnings") or [])
    return "\n".join(lines)
