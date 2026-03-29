"""Spectral Binding -- VRGB measurement axiom.

At any zoom level, divide into no more than 21 human-perceivable bands.
Split any band by discovering the midpoint. The namespace is the continuum.
Addresses are discovered, not assigned.

This module provides:
    - Band registry (Level 0 hue domains from VRGB wheel)
    - Zoom-level resolution (hex → band, siblings, depth)
    - Midpoint discovery (split any band via HSL interpolation)
    - Constellation mapping (cluster hex values by hue proximity)

Usage:
    from spectral import resolve, midpoint, constellation

    band = resolve("#3A7F2B")
    # {"hex": "#3A7F2B", "hue": 137.4, "band": "vault", "level": 0, ...}

    mid = midpoint("#3A7F2B", "#8C4DE1")
    # {"hex": "#63669A", "hue": 243.7}

    groups = constellation(["#3A7F2B", "#3B8F1C", "#D15F3A", "#D2603B"])
    # {"vault": ["#3A7F2B", "#3B8F1C"], "client": ["#D15F3A", "#D2603B"]}
"""

import colorsys
import json


# ============================================================
# PERIODIC TABLE -- first 21 elements as band labels
# ============================================================
# 21 elements = 21 max bands per level (Miller's number).
# Same labels at every zoom level. Element number = band index.
# Addresses are element paths: H.Li.B = band 1, sub 3, sub-sub 5.

ELEMENTS = [
    {"z": 1,  "symbol": "H",  "name": "Hydrogen"},
    {"z": 2,  "symbol": "He", "name": "Helium"},
    {"z": 3,  "symbol": "Li", "name": "Lithium"},
    {"z": 4,  "symbol": "Be", "name": "Beryllium"},
    {"z": 5,  "symbol": "B",  "name": "Boron"},
    {"z": 6,  "symbol": "C",  "name": "Carbon"},
    {"z": 7,  "symbol": "N",  "name": "Nitrogen"},
    {"z": 8,  "symbol": "O",  "name": "Oxygen"},
    {"z": 9,  "symbol": "F",  "name": "Fluorine"},
    {"z": 10, "symbol": "Ne", "name": "Neon"},
    {"z": 11, "symbol": "Na", "name": "Sodium"},
    {"z": 12, "symbol": "Mg", "name": "Magnesium"},
    {"z": 13, "symbol": "Al", "name": "Aluminum"},
    {"z": 14, "symbol": "Si", "name": "Silicon"},
    {"z": 15, "symbol": "P",  "name": "Phosphorus"},
    {"z": 16, "symbol": "S",  "name": "Sulfur"},
    {"z": 17, "symbol": "Cl", "name": "Chlorine"},
    {"z": 18, "symbol": "Ar", "name": "Argon"},
    {"z": 19, "symbol": "K",  "name": "Potassium"},
    {"z": 20, "symbol": "Ca", "name": "Calcium"},
    {"z": 21, "symbol": "Sc", "name": "Scandium"},
]

MAX_BANDS_PER_LEVEL = 21


def _element_for_index(index):
    """Get element symbol for a band index (0-based)."""
    if 0 <= index < len(ELEMENTS):
        return ELEMENTS[index]["symbol"]
    return str(index)


def _element_name_for_index(index):
    """Get element full name for a band index (0-based)."""
    if 0 <= index < len(ELEMENTS):
        return ELEMENTS[index]["name"]
    return "Band %d" % index


# ============================================================
# LEVEL 0 BAND REGISTRY
# ============================================================
# 6 bands at 60 degrees each. Labeled with elements 1-6.
# Each can subdivide to 21 sub-bands (Level 1), and so on.

def _build_l0_bands(n=6):
    """Build Level 0 bands from the first n elements."""
    bands = []
    step = 360.0 / n
    for i in range(n):
        bands.append({
            "name": _element_for_index(i),
            "full_name": _element_name_for_index(i),
            "index": i,
            "hue_start": i * step,
            "hue_end": (i + 1) * step,
        })
    return bands

BANDS_L0 = _build_l0_bands(6)


# ============================================================
# HEX / HSL CONVERSIONS
# ============================================================

def hex_to_rgb(hex_color):
    """Convert #RRGGBB to (r, g, b) floats 0-1."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return (0.0, 0.0, 0.0)
    r = int(h[0:2], 16) / 255.0
    g = int(h[2:4], 16) / 255.0
    b = int(h[4:6], 16) / 255.0
    return (r, g, b)


def rgb_to_hex(r, g, b):
    """Convert (r, g, b) floats 0-1 to #RRGGBB."""
    ri = max(0, min(255, int(round(r * 255))))
    gi = max(0, min(255, int(round(g * 255))))
    bi = max(0, min(255, int(round(b * 255))))
    return "#%02X%02X%02X" % (ri, gi, bi)


def hex_to_hsl(hex_color):
    """Convert #RRGGBB to (h, s, l) where h is 0-360, s and l are 0-1."""
    r, g, b = hex_to_rgb(hex_color)
    # colorsys uses HLS not HSL
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    return (h * 360.0, s, l)


def hsl_to_hex(h, s, l):
    """Convert (h, s, l) to #RRGGBB. h is 0-360, s and l are 0-1."""
    h_norm = (h % 360.0) / 360.0
    r, g, b = colorsys.hls_to_rgb(h_norm, l, s)
    return rgb_to_hex(r, g, b)


# ============================================================
# BAND RESOLUTION
# ============================================================

def _find_band(hue, bands=None):
    """Find which band a hue falls into."""
    if bands is None:
        bands = BANDS_L0
    hue = hue % 360.0
    for band in bands:
        start = band["hue_start"]
        end = band["hue_end"]
        if start <= hue < end:
            return band
        # Handle wrap-around (e.g. 350-10)
        if start > end and (hue >= start or hue < end):
            return band
    return bands[0]


def subdivide(band, n=None):
    """Subdivide a band into n equal sub-bands. Max 21.

    Sub-bands are labeled with element symbols (H through Sc).

    Args:
        band: Dict with hue_start, hue_end, name.
        n: Number of sub-bands. Defaults to MAX_BANDS_PER_LEVEL.

    Returns:
        List of sub-band dicts.
    """
    if n is None:
        n = MAX_BANDS_PER_LEVEL
    n = min(n, MAX_BANDS_PER_LEVEL)

    start = band["hue_start"]
    end = band["hue_end"]
    width = (end - start) % 360
    if width == 0:
        width = 360
    step = width / n

    parent_name = band["name"]
    subs = []
    for i in range(n):
        sub_start = (start + i * step) % 360
        sub_end = (start + (i + 1) * step) % 360
        symbol = _element_for_index(i)
        subs.append({
            "name": "%s.%s" % (parent_name, symbol),
            "symbol": symbol,
            "full_name": _element_name_for_index(i),
            "hue_start": sub_start,
            "hue_end": sub_end,
            "parent": parent_name,
            "index": i,
        })
    return subs


def resolve(hex_color):
    """Resolve a hex color to its band, hue, and position.

    Args:
        hex_color: 6-char hex with # prefix.

    Returns:
        Dict with hex, hue, saturation, lightness, band name,
        band range, position within band (0-1), siblings.
    """
    h, s, l = hex_to_hsl(hex_color)
    band = _find_band(h)

    # Position within band (0.0 = start, 1.0 = end)
    band_width = (band["hue_end"] - band["hue_start"]) % 360
    if band_width == 0:
        band_width = 360
    position = ((h - band["hue_start"]) % 360) / band_width

    # Siblings: other Level 0 bands
    siblings = [b["name"] for b in BANDS_L0 if b["name"] != band["name"]]

    return {
        "hex": hex_color.upper() if hex_color.startswith("#") else "#" + hex_color.upper(),
        "hue": round(h, 2),
        "saturation": round(s, 4),
        "lightness": round(l, 4),
        "band": band["name"],
        "element": band["name"],
        "element_name": band.get("full_name", ""),
        "band_range": [band["hue_start"], band["hue_end"]],
        "position": round(position, 4),
        "level": 0,
        "siblings": siblings,
    }


def resolve_deep(hex_color, depth=3):
    """Resolve a hex color through multiple zoom levels.

    Returns element path (e.g. "He.P.N") and per-level detail.

    Args:
        hex_color: 6-char hex with # prefix.
        depth: How many levels deep to resolve.

    Returns:
        Dict with path (element path string) and levels (list of per-level dicts).
    """
    h, s, l = hex_to_hsl(hex_color)
    levels = []
    path_parts = []
    current_bands = BANDS_L0

    for level in range(depth):
        band = _find_band(h, current_bands)
        band_width = (band["hue_end"] - band["hue_start"]) % 360
        if band_width == 0:
            band_width = 360
        position = ((h - band["hue_start"]) % 360) / band_width

        # Extract the element symbol (last part of dotted name)
        symbol = band["name"].split(".")[-1] if "." in band["name"] else band["name"]
        path_parts.append(symbol)

        levels.append({
            "level": level,
            "element": symbol,
            "element_name": band.get("full_name", ""),
            "band": band["name"],
            "band_range": [round(band["hue_start"], 4), round(band["hue_end"], 4)],
            "position": round(position, 4),
            "width_degrees": round(band_width, 4),
        })

        # Subdivide for next level
        current_bands = subdivide(band)

    return {
        "hex": hex_color.upper() if hex_color.startswith("#") else "#" + hex_color.upper(),
        "path": ".".join(path_parts),
        "levels": levels,
    }


# ============================================================
# MIDPOINT DISCOVERY
# ============================================================

def midpoint(hex_a, hex_b):
    """Find the midpoint between two hex colors in HSL space.

    Interpolates hue along the shortest arc on the hue wheel.

    Args:
        hex_a: First hex color.
        hex_b: Second hex color.

    Returns:
        Dict with hex, hue, saturation, lightness.
    """
    h_a, s_a, l_a = hex_to_hsl(hex_a)
    h_b, s_b, l_b = hex_to_hsl(hex_b)

    # Shortest arc interpolation for hue
    diff = h_b - h_a
    if diff > 180:
        diff -= 360
    elif diff < -180:
        diff += 360
    h_mid = (h_a + diff / 2) % 360

    s_mid = (s_a + s_b) / 2
    l_mid = (l_a + l_b) / 2

    hex_mid = hsl_to_hex(h_mid, s_mid, l_mid)

    return {
        "hex": hex_mid,
        "hue": round(h_mid, 2),
        "saturation": round(s_mid, 4),
        "lightness": round(l_mid, 4),
        "parents": [hex_a.upper(), hex_b.upper()],
    }


def split_band(hex_a, hex_b, n=2):
    """Split the range between two hex colors into n equal parts.

    Args:
        hex_a: Start hex color.
        hex_b: End hex color.
        n: Number of segments (produces n-1 interior points + 2 endpoints).

    Returns:
        List of hex colors from a to b, inclusive.
    """
    h_a, s_a, l_a = hex_to_hsl(hex_a)
    h_b, s_b, l_b = hex_to_hsl(hex_b)

    diff = h_b - h_a
    if diff > 180:
        diff -= 360
    elif diff < -180:
        diff += 360

    points = []
    for i in range(n + 1):
        t = i / n
        h = (h_a + diff * t) % 360
        s = s_a + (s_b - s_a) * t
        l = l_a + (l_b - l_a) * t
        points.append(hsl_to_hex(h, s, l))

    return points


# ============================================================
# HUE DISTANCE
# ============================================================

def hue_distance(hex_a, hex_b):
    """Shortest arc distance between two hex colors on the hue wheel.

    Returns:
        Float, 0-180 degrees.
    """
    h_a = hex_to_hsl(hex_a)[0]
    h_b = hex_to_hsl(hex_b)[0]
    diff = abs(h_a - h_b)
    if diff > 180:
        diff = 360 - diff
    return round(diff, 2)


# ============================================================
# CONSTELLATION MAPPING
# ============================================================

def constellation(hex_list, threshold=60.0):
    """Group hex colors by hue proximity.

    Colors within `threshold` degrees of hue are in the same cluster.
    Default threshold = 60 degrees (one Level 0 band width).

    Args:
        hex_list: List of hex color strings.
        threshold: Max hue distance to be in the same group.

    Returns:
        Dict mapping band names to lists of hex colors.
    """
    groups = {}
    for hex_color in hex_list:
        info = resolve(hex_color)
        band = info["band"]
        if band not in groups:
            groups[band] = []
        groups[band].append({
            "hex": info["hex"],
            "hue": info["hue"],
            "position": info["position"],
        })

    # Sort within each group by hue
    for band in groups:
        groups[band].sort(key=lambda x: x["hue"])

    return groups


def constellation_summary(hex_list):
    """One-line summary of a constellation.

    Args:
        hex_list: List of hex color strings.

    Returns:
        String like "3 vault, 2 client, 1 platform"
    """
    groups = constellation(hex_list)
    parts = []
    for band in sorted(groups.keys(), key=lambda b: -len(groups[b])):
        parts.append("%d %s" % (len(groups[band]), band))
    return ", ".join(parts)


# ============================================================
# REGISTRY
# ============================================================

def registry():
    """Return the full Level 0 band registry."""
    return list(BANDS_L0)


def registry_json():
    """Return the registry as formatted JSON."""
    return json.dumps(BANDS_L0, indent=2)


# ============================================================
# CLI
# ============================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Spectral Binding -- VRGB measurement axiom")
        print("")
        print("Usage:")
        print("  spectral.py resolve #3A7F2B              Resolve hex to band")
        print("  spectral.py resolve-deep #3A7F2B [depth] Multi-level resolution")
        print("  spectral.py midpoint #3A7F2B #8C4DE1     Find midpoint")
        print("  spectral.py split #3A7F2B #8C4DE1 [n]    Split range into n parts")
        print("  spectral.py distance #3A7F2B #8C4DE1     Hue distance in degrees")
        print("  spectral.py constellation #AA #BB #CC     Group by proximity")
        print("  spectral.py registry                      Show Level 0 bands")
        print("  spectral.py subdivide <band_name> [n]     Subdivide a band")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "resolve":
        print(json.dumps(resolve(sys.argv[2]), indent=2))

    elif cmd == "resolve-deep":
        depth = int(sys.argv[3]) if len(sys.argv) > 3 else 3
        result = resolve_deep(sys.argv[2], depth)
        print(json.dumps(result, indent=2))

    elif cmd == "midpoint":
        print(json.dumps(midpoint(sys.argv[2], sys.argv[3]), indent=2))

    elif cmd == "split":
        n = int(sys.argv[4]) if len(sys.argv) > 4 else 2
        points = split_band(sys.argv[2], sys.argv[3], n)
        for p in points:
            info = resolve(p)
            print("  %s  hue=%.1f  band=%s" % (p, info["hue"], info["band"]))

    elif cmd == "distance":
        d = hue_distance(sys.argv[2], sys.argv[3])
        print("%.2f degrees" % d)

    elif cmd == "constellation":
        hexes = sys.argv[2:]
        groups = constellation(hexes)
        print(json.dumps(groups, indent=2))
        print("")
        print("Summary: %s" % constellation_summary(hexes))

    elif cmd == "registry":
        for band in BANDS_L0:
            print("  %3d-%3d  %-4s %s" % (
                band["hue_start"], band["hue_end"],
                band["name"], band.get("full_name", "")
            ))

    elif cmd == "subdivide":
        band_name = sys.argv[2]
        n = int(sys.argv[3]) if len(sys.argv) > 3 else MAX_BANDS_PER_LEVEL
        band = None
        for b in BANDS_L0:
            if b["name"] == band_name:
                band = b
                break
        if not band:
            print("Unknown band: %s" % band_name)
            sys.exit(1)
        subs = subdivide(band, n)
        for s in subs:
            print("  %7.2f-%7.2f  %s" % (s["hue_start"], s["hue_end"], s["name"]))

    else:
        print("Unknown command: %s" % cmd)
        sys.exit(1)
