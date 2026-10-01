#!/usr/bin/env python3
"""Geometry checks for the Pomona sensor mounts (standard library only).

Run after rendering the STLs (see ../README.md):
    python3 hardware/a1mini-sensor-station/tests/check_geometry.py

Checks, per mount:
  1. Rail slot clear: sample points inside the station's T-rail (seated in the socket) are empty.
  2. Vessel clear: no vertex lies inside the 76 mm vessel wall behind the socket.
  3. Bore clear: sample points along the probe / hose / board path are empty.
  4. Closed mesh: every edge is shared by exactly two triangles.
  5. Fits the Bambu A1 mini bed (180 x 180 x 180 mm) and starts at Z = 0.
  6. Supportless: no downward-facing area steeper than 45 degrees above the bed, except short
     bridges (reported, and limited per part).
Values must match src/pomona_sensor_mounts.scad defaults.

Probe lid (src/pomona_probe_lid.scad, print orientation, top face on the bed), per container size:
  pot, probe, hose and level ports open; lid plate solid elsewhere (blocks light); nothing below
  the rim reaches outside the skirt (it drops into the opening); skirt diameter; closed mesh;
  fits the bed; supportless. Extra sizes: --lid-variant ID:PATH (build.sh renders 90 and 150 mm).
"""
import math
import struct
import sys
from pathlib import Path

STL_DIR = Path(__file__).resolve().parents[1] / "stl"
FRONT, OVERLAP, WALL = 3.4, 1.0, 2.7
RAIL_TO_VESSEL_X = 40.8   # socket x = 0 sits on the rail head's back face, 40.8 mm from vessel axis
VESSEL_R = 38.0           # body_od 76 in pomona_dual_station_v1.scad


def load(path):
    data = path.read_bytes()
    if data[:5] == b"solid" and b"facet" in data[:400]:
        tris, v = [], []
        for line in data.decode().splitlines():
            t = line.split()
            if t and t[0] == "vertex":
                v.append(tuple(float(x) for x in t[1:4]))
                if len(v) == 3:
                    tris.append(v)
                    v = []
        return tris
    n = struct.unpack("<I", data[80:84])[0]
    out = []
    for i in range(n):
        f = struct.unpack("<12f", data[84 + 50 * i: 84 + 50 * i + 48])
        out.append([f[3:6], f[6:9], f[9:12]])
    return out


def inside(tris, p, d=(0.00031, 1.0, 0.00047)):
    hits = 0
    for a, b, c in tris:
        e1 = [b[i] - a[i] for i in range(3)]
        e2 = [c[i] - a[i] for i in range(3)]
        h = [d[1] * e2[2] - d[2] * e2[1], d[2] * e2[0] - d[0] * e2[2], d[0] * e2[1] - d[1] * e2[0]]
        det = sum(e1[i] * h[i] for i in range(3))
        if abs(det) < 1e-12:
            continue
        f = 1 / det
        s = [p[i] - a[i] for i in range(3)]
        u = f * sum(s[i] * h[i] for i in range(3))
        if u < 0 or u > 1:
            continue
        q = [s[1] * e1[2] - s[2] * e1[1], s[2] * e1[0] - s[0] * e1[2], s[0] * e1[1] - s[1] * e1[0]]
        v = f * sum(d[i] * q[i] for i in range(3))
        if v < 0 or u + v > 1:
            continue
        if f * sum(e2[i] * q[i] for i in range(3)) > 1e-9:
            hits += 1
    return hits % 2 == 1


def rail_points(h):
    # Rail head 11.0 x 1.6 seated at socket x 0..1.6, neck 8.0 wide from x -1.4 to 0 (shrunk 0.1 mm).
    pts = []
    for z in [0.5, h / 2, h - 0.5]:
        for x in [0.1, 0.8, 1.5]:
            for y in [-5.4, -2.7, 0, 2.7, 5.4]:
                pts.append((x, y, z))
        for x in [-1.3, -0.7, -0.1]:
            for y in [-3.9, 0, 3.9]:
                pts.append((x, y, z))
    return pts


def circle_points(cx, cy, r, zs, frac=0.85):
    return [(cx + frac * r * math.cos(a), cy + frac * r * math.sin(a), z) for z in zs
            for a in [i * math.pi / 4 for i in range(8)]] + [(cx, cy, z) for z in zs]


def edges_manifold(tris):
    count = {}
    for t in tris:
        pts = [tuple(round(c, 4) for c in v) for v in t]
        for i in range(3):
            e = tuple(sorted((pts[i], pts[(i + 1) % 3])))
            count[e] = count.get(e, 0) + 1
    return sum(1 for n in count.values() if n != 2)


def overhang_area(tris, limit_deg=45.0):
    area = 0.0
    for a, b, c in tris:
        e1 = [b[i] - a[i] for i in range(3)]
        e2 = [c[i] - a[i] for i in range(3)]
        n = [e1[1] * e2[2] - e1[2] * e2[1], e1[2] * e2[0] - e1[0] * e2[2], e1[0] * e2[1] - e1[1] * e2[0]]
        length = math.sqrt(sum(x * x for x in n))
        if length == 0 or min(a[2], b[2], c[2]) < 0.05:
            continue
        if -n[2] / length > math.cos(math.radians(limit_deg)):
            area += length / 2
    return area


PH_BORE = 12.6 / 2
DS_BORE = 6.6 / 2
PARTS = {
    "rail_fit": {"socket_h": 12, "bores": [], "max_overhang": 0},
    "ph": {"socket_h": 28, "bores": circle_points(FRONT - OVERLAP + PH_BORE + WALL, 0, PH_BORE, [1, 14, 27, 39]),
           "max_overhang": 0},
    "ds18b20": {"socket_h": 22, "bores": circle_points(FRONT - OVERLAP + DS_BORE + WALL, 0, DS_BORE, [1, 11, 21, 27]),
                "max_overhang": 0},
    "hose": {"socket_h": 16, "bores": circle_points(FRONT - OVERLAP + 3.2 + WALL, 0, 3.2, [1, 8, 15]),
             "max_overhang": 0},
    "moisture": {"socket_h": 22, "bores": [(FRONT - OVERLAP + WALL + 1.1, y, z) for y in (-11.5, -6, 0, 6, 11.5)
                                           for z in (1, 15, 29)], "max_overhang": 0},
    # Cage roof and vent slot tops are short bridges.
    "sht31": {"socket_h": 22, "bores": [(FRONT - OVERLAP + x, y, 60 + z) for x in (4, 12, 20) for y in (-5, 0, 5)
                                        for z in (4, 10, 16)], "max_overhang": 700},
}


def lid_layout(cid):
    """Mirror of pomona_probe_lid.scad defaults for container inside diameter `cid`."""
    return {
        "lid_t": 3.0, "skirt_h": 10.0, "sleeve_h": 18.0, "lid_d": cid + 8.0, "skirt_od": cid - 0.6,
        "holes": {"pot": ((-0.14 * cid, 0), 50.4 / 2), "ph": ((0.27 * cid, 0), 12.6 / 2),
                  "ds18b20": ((0.20 * cid, 0.20 * cid), 6.6 / 2), "hose": ((0.20 * cid, -0.20 * cid), 6.4 / 2),
                  "level": ((0.06 * cid, 0.36 * cid), 8.4 / 2)},
        "sleeves": ("ph", "ds18b20", "hose"),
    }


def check_lid(path, cid):
    L = lid_layout(cid)
    tris = load(path)
    vs = [v for t in tris for v in t]
    lo = [min(v[i] for v in vs) for i in range(3)]
    hi = [max(v[i] for v in vs) for i in range(3)]
    size = [hi[i] - lo[i] for i in range(3)]
    t = L["lid_t"]
    blocked = []
    for name, ((x, y), r) in L["holes"].items():
        top = t + L["sleeve_h"] if name in L["sleeves"] else t
        zs = [0.3, t / 2, t - 0.3] + ([t + 1, t + L["sleeve_h"] / 2, top - 0.5] if name in L["sleeves"] else [])
        blocked += [(name, p) for p in circle_points(x, y, r, zs, frac=0.8) if inside(tris, p)]
    # Light block: the plate is solid away from every hole.
    solid_pts = []
    for gx in range(-60, 61, 6):
        for gy in range(-60, 61, 6):
            if math.hypot(gx, gy) > L["lid_d"] / 2 - 1.5:
                continue
            if any(math.hypot(gx - x, gy - y) < r + 1.2 for (x, y), r in L["holes"].values()):
                continue
            solid_pts.append((gx, gy, t / 2))
    leaks = [p for p in solid_pts if not inside(tris, p)]
    below_rim = [math.hypot(v[0], v[1]) for v in vs if v[2] > t + 0.05]
    skirt = [math.hypot(v[0], v[1]) for v in vs if t + 0.05 < v[2] <= t + L["skirt_h"] + 0.05]
    checks = {
        "ports open": not blocked,
        "plate solid": not leaks and len(solid_pts) > 50,
        "drops into opening": max(below_rim) <= L["skirt_od"] / 2 + 1e-3,
        "skirt diameter": abs(2 * max(skirt) - L["skirt_od"]) < 0.1,
        "sleeve length": abs(hi[2] - (t + L["sleeve_h"])) < 1e-3,
        "closed mesh": edges_manifold(tris) == 0,
        "fits A1 mini": size[0] <= 180 and size[1] <= 180 and abs(lo[2]) < 1e-6,
        "supportless": overhang_area(tris) <= 1.0,
    }
    ok = all(checks.values())
    print(f"lid {cid:5.1f} {'ok' if ok else 'FAIL':4s} size {size[0]:5.1f} x {size[1]:5.1f} x {size[2]:5.1f} mm, "
          f"{len(tris)} triangles, {len(solid_pts)} solid samples "
          + " ".join(f"[{k}]" for k, good in checks.items() if not good))
    if blocked:
        print("   port blocked:", [(n, tuple(round(c, 2) for c in p)) for n, p in blocked[:3]])
    if leaks:
        print("   plate open at:", leaks[:3])
    return ok


def main():
    failures = []
    if not check_lid(STL_DIR / "pomona_probe_lid_v1.stl", 110.0):
        failures.append("lid")
    for arg in sys.argv[1:]:
        if arg.startswith("--lid-variant="):
            cid, path = arg.split("=", 1)[1].split(":", 1)
            if not check_lid(Path(path), float(cid)):
                failures.append(f"lid {cid}")
    for name, spec in PARTS.items():
        path = STL_DIR / f"pomona_v6_3_{name}.stl"
        tris = load(path)
        vs = [v for t in tris for v in t]
        lo = [min(v[i] for v in vs) for i in range(3)]
        hi = [max(v[i] for v in vs) for i in range(3)]
        rail_hits = [p for p in rail_points(spec["socket_h"]) if inside(tris, p)]
        vessel_hits = [v for v in vs if math.hypot(v[0] + RAIL_TO_VESSEL_X, v[1]) < VESSEL_R - 1e-6]
        bore_hits = [p for p in spec["bores"] if inside(tris, p)]
        open_edges = edges_manifold(tris)
        size = [hi[i] - lo[i] for i in range(3)]
        overhang = overhang_area(tris)
        checks = {
            "rail slot clear": not rail_hits,
            "vessel clear": not vessel_hits and lo[0] >= -1.4 - 1e-6,
            "bore clear": not bore_hits,
            "closed mesh": open_edges == 0,
            "fits A1 mini": all(s <= 180 for s in size) and abs(lo[2]) < 1e-6,
            "supportless": overhang <= spec["max_overhang"],
        }
        status = "ok" if all(checks.values()) else "FAIL"
        print(f"{name:9s} {status:4s} size {size[0]:5.1f} x {size[1]:5.1f} x {size[2]:5.1f} mm, "
              f"{len(tris)} triangles, overhang {overhang:5.1f} mm2 "
              + " ".join(f"[{k}]" for k, ok in checks.items() if not ok))
        if status != "ok":
            failures.append(name)
            if rail_hits: print("   rail slot blocked at", rail_hits[:3])
            if bore_hits: print("   bore blocked at", [tuple(round(c, 2) for c in p) for p in bore_hits[:3]])
            if vessel_hits: print("   inside vessel wall:", vessel_hits[:3])
    plate = load(STL_DIR / "pomona_v6_3_plate.stl")
    pv = [v for t in plate for v in t]
    span = [max(v[i] for v in pv) - min(v[i] for v in pv) for i in range(3)]
    fits = all(0 <= min(v[i] for v in pv) and max(v[i] for v in pv) <= 180 for i in range(2))
    print(f"plate     {'ok' if fits else 'FAIL'}  footprint {span[0]:.1f} x {span[1]:.1f} mm on the 180 x 180 bed")
    if not fits:
        failures.append("plate")
    if failures:
        print("FAILED:", ", ".join(failures))
        return 1
    print("all mounts and lid sizes pass")
    return 0


if __name__ == "__main__":
    sys.exit(main())
