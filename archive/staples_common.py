#!/usr/bin/env python3
"""
DiscoverAI: Shared helpers for staples generator/import scripts
====================================================================

Common logic reused by the Atta, Cooking Oil & Ghee, Sugar & Salt, and
Besan & Other Flours generator/import scripts, so pack-size/quantity/unit
parsing (and the bugs that come with re-typing it) only lives in one place.
Not imported by the earlier vegetable/fruit/rice/pulses scripts - those
stay as-is, this is just for the 4 new categories going forward.
"""

import json
import math
import re

PACK_SIZE_RE = re.compile(r'\(([^)]*)\)\s*$')
WEIGHT_VOLUME_RE = re.compile(r'(\d+(?:\.\d+)?)\s*(kg|kgs|g|gm|gms|gram|grams|ml|l|litre|liter|ltr)\b', re.IGNORECASE)
QUANTITY_WEIGHT_VOLUME_RE = re.compile(r'^(\d+(?:\.\d+)?)\s*(kg|g|ml|l)$', re.IGNORECASE)
_VOLUME_UNIT_MAP = {"ml": "ml", "l": "L", "ltr": "L", "litre": "L", "liter": "L"}


def bulk_factor(qty, anchor):
    """~7% cheaper per doubling of pack size (matches earlier batches)."""
    doublings = math.log2(qty / anchor)
    return 0.933 ** doublings


def format_pack_label(qty, base_unit):
    """base_unit is 'g' or 'ml'. Renders e.g. 500 g -> '500g', 1000 g -> '1 kg',
    500 ml -> '500ml', 1000 ml -> '1L'."""
    if base_unit == "g":
        if qty >= 1000 and qty % 1000 == 0:
            kg = qty // 1000
            return f"{kg} kg" if kg > 1 else "1 kg"
        return f"{int(qty)}g" if qty == int(qty) else f"{qty}g"
    if base_unit == "ml":
        if qty >= 1000 and qty % 1000 == 0:
            liters = qty // 1000
            return f"{liters}L" if liters > 1 else "1L"
        return f"{int(qty)}ml" if qty == int(qty) else f"{qty}ml"
    raise ValueError(f"unknown base_unit {base_unit!r}")


def derive_pack_size(name):
    """Pull the trailing parenthetical weight/volume out of a product name,
    e.g. 'Aashirvaad Atta (5 kg)' -> '5kg', 'Fortune Oil (500ml)' -> '500ml'."""
    m = PACK_SIZE_RE.search(name or "")
    if not m:
        return None
    inside = m.group(1)
    wm = WEIGHT_VOLUME_RE.search(inside)
    if not wm:
        return inside.strip() or None
    qty, unit = wm.groups()
    unit_l = unit.lower()
    if unit_l.startswith("kg"):
        norm_unit = "kg"
    elif unit_l in ("l", "ltr", "litre", "liter"):
        norm_unit = "L"
    elif unit_l == "ml":
        norm_unit = "ml"
    else:
        norm_unit = "g"
    qty_num = float(qty)
    qty_str = str(int(qty_num)) if qty_num == int(qty_num) else str(qty_num)
    return f"{qty_str}{norm_unit}"


def derive_quantity_unit(pack_size):
    """'250g' -> (250, 'gm'); '1kg' -> (1, 'kg'); '500ml' -> (500, 'ml');
    '1L' -> (1, 'L'). Returns (None, None) if unparseable."""
    if not pack_size:
        return None, None
    m = QUANTITY_WEIGHT_VOLUME_RE.match(pack_size.strip())
    if not m:
        return None, None
    qty_str, unit = m.groups()
    qty = float(qty_str)
    if qty == int(qty):
        qty = int(qty)
    unit_l = unit.lower()
    if unit_l == "kg":
        return qty, "kg"
    if unit_l == "g":
        return qty, "gm"
    return qty, _VOLUME_UNIT_MAP[unit_l]


def derive_organic(name, brand):
    name_l = (name or "").lower()
    brand_l = (brand or "").lower()
    return "organic" in name_l or "organic" in brand_l


def derive_marker(name, markers, default):
    """markers: list of (substring, label) checked longest-first (caller's
    responsibility to order them). Returns the first match's label, or
    `default` if nothing matches."""
    name_l = (name or "").lower()
    for marker, label in markers:
        if marker.lower() in name_l:
            return label
    return default


def parse_bool(value):
    return str(value).strip().lower() in ("t", "true", "1", "yes")


def build_variant_name(brand, variety, organic, organic_locked, extra_tag, pack_label):
    """e.g. build_variant_name('Fortune', 'Sunflower Oil', True, False,
    'Cold-Pressed', '1L') -> 'Organic Cold-Pressed Fortune Sunflower Oil (1L)'"""
    parts = []
    if organic and not (organic_locked and "organic" in brand.lower()):
        parts.append("Organic")
    if extra_tag:
        parts.append(extra_tag)
    parts.append(f"{brand} {variety}")
    return f"{' '.join(parts)} ({pack_label})"
