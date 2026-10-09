"""Tornado check for one location — used by Claude in loop mode.

Pulls three things and prints a short report:
  1. Official NWS alerts for the point (and any Tornado Warning within ~60 mi)
  2. NEXRAD storm cells near the point, with the radar's own rotation
     detections (TVS = tornado vortex signature, MESO = mesocyclone rank 1-25),
     storm motion, and how close each cell will pass and when
  3. A storm-relative velocity + reflectivity image cropped around the most
     concerning cell (or home), so a human/Claude can look for a
     velocity couplet (bright green next to bright red) and a hook echo

The "suggested level" uses the same rules as the app's AI storm watch.
It is a second opinion only — NWS warnings always come first.

Usage:  python tools/tornado_check.py --lat 35.47 --lon -97.52 --label "Home"
        or put {"lat": .., "lon": .., "label": ".."} in tools/home.json (git-ignored,
        so your home location never gets pushed) and run it with no arguments.
        --alarm-level 3  sounds tools/alarm.ps1 (siren + voice + pop-up) when the level
        reaches 3 or 4; it re-alarms only if the level goes up or a new warning is issued.
Needs:  pip install pillow   (only for the velocity image)
"""
import argparse, json, math, os, subprocess, sys, urllib.request
from datetime import datetime, timezone

UA = {"User-Agent": "weather-app tornado_check (github.com/cleetus/weather-app)"}
IEM = "https://mesonet.agron.iastate.edu"
LEVELS = ["All clear", "Stay alert", "Rotation nearby - watch closely",
          "Tornado threat - would warn", "TORNADO WARNING - take shelter"]


def get(url, binary=False):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=25) as r:
        data = r.read()
    return data if binary else json.loads(data)


def miles(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    a = (math.sin((lat2 - lat1) * p / 2) ** 2
         + math.cos(lat1 * p) * math.cos(lat2 * p) * math.sin((lon2 - lon1) * p / 2) ** 2)
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def bearing(lat1, lon1, lat2, lon2):
    p = math.pi / 180
    y = math.sin((lon2 - lon1) * p) * math.cos(lat2 * p)
    x = (math.cos(lat1 * p) * math.sin(lat2 * p)
         - math.sin(lat1 * p) * math.cos(lat2 * p) * math.cos((lon2 - lon1) * p))
    return (math.atan2(y, x) / p + 360) % 360


def compass(deg):
    return ["N", "NE", "E", "SE", "S", "SW", "W", "NW"][round(deg / 45) % 8]


def track(cell, lat, lon):
    """Closest approach (miles) and minutes until then, assuming the cell keeps its motion.
    Radar storm motion 'drct' is the direction it is moving FROM."""
    c = cell["geometry"]["coordinates"]
    p = cell["properties"]
    dist = miles(lat, lon, c[1], c[0])
    brg = bearing(lat, lon, c[1], c[0])                 # home -> cell
    mph = (p.get("sknt") or 0) * 1.15078
    # flat-earth: home at origin, x east / y north, in miles
    x, y = dist * math.sin(math.radians(brg)), dist * math.cos(math.radians(brg))
    if mph < 3:
        return dist, brg, mph, None, dist, None
    to = math.radians(((p.get("drct") or 0) + 180) % 360)
    vx, vy = mph * math.sin(to), mph * math.cos(to)     # miles per hour
    t = -(x * vx + y * vy) / (vx * vx + vy * vy)        # hours to closest approach
    if t <= 0:
        return dist, brg, mph, (math.degrees(to) % 360), dist, None  # moving away
    cpa = math.hypot(x + vx * t, y + vy * t)
    return dist, brg, mph, (math.degrees(to) % 360), cpa, t * 60


def rotation(p):
    tvs = (p.get("tvs") or "NONE").upper()
    meso = p.get("meso") or "NONE"
    rank = int(meso) if str(meso).isdigit() else 0
    return tvs if tvs != "NONE" else None, rank


def save_velocity_image(radar, clat, clon, home, cells, out_dir, radius_mi=45):
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None, "pip install pillow to get the velocity image"
    os.makedirs(out_dir, exist_ok=True)
    panels, valid = [], ""
    for prod in ("N0S", "N0B"):
        base = f"{IEM}/data/gis/images/4326/ridge/{radar}/{prod}_0"
        img = Image.open(__import__("io").BytesIO(get(base + ".png", binary=True))).convert("RGBA")
        wld = [float(v) for v in get(base + ".wld", binary=True).decode().split()]
        try:
            valid = get(base + ".json")["meta"]["valid"]
        except Exception:
            pass
        dx, dy, x0, y0 = wld[0], wld[3], wld[4], wld[5]
        rlat = radius_mi / 69.0
        rlon = radius_mi / (69.0 * math.cos(math.radians(clat)))
        box = (int((clon - rlon - x0) / dx), int((clat + rlat - y0) / dy),
               int((clon + rlon - x0) / dx), int((clat - rlat - y0) / dy))
        crop = img.crop(box)
        bg = Image.new("RGBA", crop.size, (20, 20, 28, 255))
        bg.alpha_composite(crop)
        size = 640  # both products have different pixel sizes; draw them the same size
        sx, sy = size / bg.width, size / bg.height
        bg = bg.resize((size, size), Image.NEAREST)
        d = ImageDraw.Draw(bg)

        def px(lat, lon):
            return ((lon - x0) / dx - box[0]) * sx, ((lat - y0) / dy - box[1]) * sy

        hx, hy = px(*home)
        d.ellipse([hx - 7, hy - 7, hx + 7, hy + 7], outline="white", width=3)
        d.text((hx + 10, hy - 6), "HOME", fill="white")
        for c in cells:
            cx, cy = px(c["lat"], c["lon"])
            col = "magenta" if c["tvs"] else ("yellow" if c["meso"] else "cyan")
            d.rectangle([cx - 5, cy - 5, cx + 5, cy + 5], outline=col, width=2)
            d.text((cx + 8, cy + 4), c["id"], fill=col)
        d.text((6, 4), f"{radar} {'STORM-REL VELOCITY' if prod == 'N0S' else 'REFLECTIVITY'}",
               fill="white")
        panels.append(bg)
    sheet = Image.new("RGBA", (sum(p.width for p in panels) + 8, max(p.height for p in panels)),
                      (0, 0, 0, 255))
    sheet.paste(panels[0], (0, 0))
    sheet.paste(panels[1], (panels[0].width + 8, 0))
    path = os.path.join(out_dir, "velocity_latest.png")
    sheet.convert("RGB").save(path)
    return path, valid


def main():
    ap = argparse.ArgumentParser()
    home_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "home.json")
    home = json.load(open(home_file)) if os.path.exists(home_file) else {}
    ap.add_argument("--lat", type=float, default=home.get("lat"))
    ap.add_argument("--lon", type=float, default=home.get("lon"))
    ap.add_argument("--label", default=home.get("label", "Home"))
    ap.add_argument("--radius", type=float, default=120, help="miles to look for storm cells")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"))
    ap.add_argument("--alarm-level", type=int, default=0, help="sound the loud alarm at this level or higher (0 = never)")
    a = ap.parse_args()
    if a.lat is None or a.lon is None:
        ap.error("give --lat and --lon, or create tools/home.json")
    lat, lon = a.lat, a.lon
    now = datetime.now(timezone.utc)
    print(f"TORNADO CHECK  {a.label} ({lat:.3f}, {lon:.3f})  {now:%Y-%m-%d %H:%MZ}")

    # 1. Official alerts
    level, reasons = 0, []
    here = get(f"https://api.weather.gov/alerts/active?point={lat},{lon}")["features"]
    events = [f["properties"]["event"] for f in here]
    print("\nNWS alerts here:", ", ".join(events) if events else "none")
    warning_ids = [f["properties"]["id"] for f in here if f["properties"]["event"] == "Tornado Warning"]
    if "Tornado Warning" in events:
        level, reasons = 4, ["NWS Tornado Warning is in effect for this location"]
    if "Tornado Watch" in events:
        level = max(level, 1); reasons.append("Tornado Watch in effect")
    if any("Hurricane" in e or "Tropical Storm" in e for e in events):
        level = max(level, 1); reasons.append("Tropical system: rain bands can spin up quick, brief tornadoes")
    tw = get("https://api.weather.gov/alerts/active?event=Tornado%20Warning")["features"]
    near_tw = []
    for f in tw:
        g = f.get("geometry")
        if not g:
            continue
        ring = g["coordinates"][0]
        clat = sum(p[1] for p in ring) / len(ring)
        clon = sum(p[0] for p in ring) / len(ring)
        d = miles(lat, lon, clat, clon)
        if d <= 60:
            near_tw.append((d, compass(bearing(lat, lon, clat, clon)), f["properties"]["areaDesc"],
                            f["properties"].get("expires", "")))
    for d, way, area, exp in sorted(near_tw):
        print(f"  Nearby Tornado Warning ~{d:.0f} mi {way}: {area} (expires {exp[11:16]} local)")
    if near_tw and level < 4:
        level = max(level, 2); reasons.append(f"{len(near_tw)} Tornado Warning(s) within 60 mi")

    # 2. Radar storm cells
    attr = get(f"{IEM}/geojson/nexrad_attr.geojson")["features"]
    seen, cells = {}, []
    for f in attr:
        c = f["geometry"]["coordinates"]
        d = miles(lat, lon, c[1], c[0])
        if d > a.radius:
            continue
        p = f["properties"]
        tvs, rank = rotation(p)
        dist, brg, mph, to, cpa, eta = track(f, lat, lon)
        cell = dict(id=f"{p['nexrad']}-{p['storm_id']}", radar=p["nexrad"], lat=c[1], lon=c[0],
                    dist=dist, brg=brg, mph=mph, to=to, cpa=cpa, eta=eta, tvs=tvs, meso=rank,
                    dbz=p.get("max_dbz"), vil=p.get("vil"), top=p.get("top"), valid=p.get("valid", ""))
        # the same storm is often seen by 2+ radars; keep the strongest report within 6 mi
        key = next((k for k in seen if miles(k[0], k[1], c[1], c[0]) < 6), None)
        if key:
            old = seen[key]
            if (bool(tvs), rank) > (bool(old["tvs"]), old["meso"]):
                cells[cells.index(old)] = cell; seen[key] = cell
            continue
        seen[(c[1], c[0])] = cell
        cells.append(cell)

    def threat(c):
        s = (100 if c["tvs"] else 0) + c["meso"] * 6
        if c["eta"] is not None and c["cpa"] < 15:
            s += 30 - c["cpa"]
        return s - c["dist"] / 4

    cells.sort(key=threat, reverse=True)
    rot = [c for c in cells if c["tvs"] or c["meso"]]
    print(f"\nRadar cells within {a.radius:.0f} mi: {len(cells)}  (with rotation: {len(rot)})")
    for c in cells[:8]:
        rot_s = c["tvs"] or (f"MESO rank {c['meso']}" if c["meso"] else "no rotation")
        mv = (f"moving {compass(c['to'])} {c['mph']:.0f} mph" if c["to"] is not None else "nearly stationary")
        if c["eta"] is not None:
            pass_s = f"closest pass {c['cpa']:.0f} mi in {c['eta']:.0f} min"
        else:
            pass_s = "not approaching"
        print(f"  {c['id']:8} {c['dist']:5.0f} mi {compass(c['brg']):2}  {rot_s:14} {c['dbz']} dBZ  "
              f"VIL {c['vil']}  top {c['top']}k ft  {mv}; {pass_s}")

        heading = c["eta"] is not None and c["cpa"] <= 10 and c["eta"] <= 60
        if c["tvs"] and c["dist"] <= 40 and heading:
            level = max(level, 3); reasons.append(f"{c['id']}: radar tornado signature headed this way")
        elif c["tvs"] and c["dist"] <= 60:
            level = max(level, 2); reasons.append(f"{c['id']}: radar tornado signature {c['dist']:.0f} mi away")
        elif c["meso"] >= 5 and c["dist"] <= 40 and heading:
            level = max(level, 2); reasons.append(f"{c['id']}: rotating storm (rank {c['meso']}) headed this way")
        elif c["meso"] >= 5 and c["dist"] <= 60:
            level = max(level, 1); reasons.append(f"{c['id']}: rotating storm {c['dist']:.0f} mi away")
    if cells:
        print(f"  (radar data time {cells[0]['valid'][11:16]}Z)")

    # 3. Velocity image around the worst cell (or home)
    focus = rot[0] if rot and rot[0]["dist"] <= 80 else None
    nexrad = get(f"{IEM}/geojson/network/NEXRAD.geojson")["features"]
    clat, clon = (focus["lat"], focus["lon"]) if focus else (lat, lon)
    radar = (focus["radar"] if focus else
             min(nexrad, key=lambda f: miles(clat, clon, f["geometry"]["coordinates"][1],
                                             f["geometry"]["coordinates"][0]))["id"])
    try:
        path, valid = save_velocity_image(radar, clat, clon, (lat, lon),
                                          [c for c in cells if miles(clat, clon, c["lat"], c["lon"]) < 50],
                                          a.out)
        print(f"\nVelocity image ({radar}, {valid[11:16]}Z, centered on "
              f"{focus['id'] if focus else 'home'}): {path}")
    except Exception as e:
        print(f"\nVelocity image unavailable: {e}")

    print(f"\nSUGGESTED LEVEL {level}: {LEVELS[level]}")
    for r in dict.fromkeys(reasons):
        print("  -", r)
    if a.alarm_level:
        maybe_alarm(level, list(dict.fromkeys(reasons)), warning_ids, a)


def maybe_alarm(level, reasons, warning_ids, a):
    """Loud alarm, but only once per threat: again only if the level goes up or NWS issues a new warning."""
    state_file = os.path.join(a.out, "alarm_state.json")
    try:
        state = json.load(open(state_file))
    except Exception:
        state = {"level": 0, "warnings": []}
    new_warning = any(w not in state["warnings"] for w in warning_ids)
    if level >= a.alarm_level and (level > state["level"] or new_warning):
        msg = ("Tornado warning for your home. Take shelter now."
               if level == 4 else "Tornado threat headed toward your home. Get ready to take shelter.")
        if reasons:
            msg += " " + reasons[0] + "."
        ps1 = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alarm.ps1")
        subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", ps1, "-Message", msg])
        print("ALARM SOUNDED:", msg)
    os.makedirs(a.out, exist_ok=True)
    # once things calm down (level 0), forget old warnings so the next storm alarms again
    json.dump({"level": level, "warnings": sorted(set(state["warnings"]) | set(warning_ids)) if level else []},
              open(state_file, "w"))


if __name__ == "__main__":
    if sys.stdout is None:   # started by pythonw (Task Scheduler): log to a file instead
        os.makedirs(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out"), exist_ok=True)
        sys.stdout = sys.stderr = open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "out",
                                                    "last_check.txt"), "w", encoding="utf-8")
    try:
        main()
    except Exception as e:
        print("CHECK FAILED:", e)
        sys.exit(1)
