"""Wind check for home — used by Claude in loop mode alongside tornado_check.py.

Reads the latest wind and gusts from the airports within ~35 mi of home (Iowa
Environmental Mesonet + NWS), plus the forecast-model wind for the exact spot.
Prints REPORT DUE when it has been 15+ minutes since the last report, and
WIND ALERT when an observed wind or gust near home goes over the limit
(again only if a later reading beats the last alerted value by 5+ mph).

Usage:  python tools/wind_check.py [--limit 50]     (reads tools/home.json)
"""
import argparse, json, os, time, urllib.request
import tornado_check as t

HERE = os.path.dirname(os.path.abspath(__file__))
KT = 1.15078


def get(url):
    return t.get(url)   # same retrying download as tornado_check


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=float, default=50, help="alert above this many mph")
    ap.add_argument("--radius", type=float, default=35, help="miles to look for stations")
    a = ap.parse_args()
    home = json.load(open(os.path.join(HERE, "home.json")))
    lat, lon = home["lat"], home["lon"]

    rows, top = [], 0
    stations = get(f"{t.IEM}/geojson/network/AL_ASOS.geojson")["features"]
    for f in stations:
        c = f["geometry"]["coordinates"]
        d = t.miles(lat, lon, c[1], c[0])
        if d > a.radius:
            continue
        sid = f["id"]
        try:
            ob = get(f"{t.IEM}/json/current.py?station={sid}&network=AL_ASOS")["last_ob"]
        except Exception:
            continue
        wind = ob.get("windspeed[kt]")
        gust = ob.get("windgust[kt]")
        # IEM often lacks the gust; the NWS feed usually has it
        try:
            p = get(f"https://api.weather.gov/stations/K{sid}/observations/latest")["properties"]
            if p["windGust"]["value"] is not None:
                gust = max(gust or 0, p["windGust"]["value"] / 1.852)
        except Exception:
            pass
        w = round(wind * KT) if wind is not None else None
        g = round(gust * KT) if gust else None
        top = max(top, w or 0, g or 0)
        rows.append((d, f["properties"]["sname"], w, g, ob.get("winddirection[deg]"), ob.get("local_valid", "")[11:16]))

    print("WIND near home (observed):")
    for d, name, w, g, wd, tm in sorted(rows):
        dirs = t.compass(wd) if wd is not None else "?"
        print(f"  {name} ({d:.0f} mi): {w if w is not None else '?'} mph from {dirs}, gust "
              f"{g if g is not None else 'n/a'} mph at {tm}")
    try:   # the forecast is extra; observed wind and the alert must still work without it
        m = get(f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&current=wind_speed_10m,wind_gusts_10m&hourly=wind_gusts_10m&forecast_hours=6"
                "&wind_speed_unit=mph&timezone=America/Chicago")
        print(f"  Forecast for home now: {m['current']['wind_speed_10m']:.0f} mph, gusts "
              f"{m['current']['wind_gusts_10m']:.0f} mph; next 6 h peak gust "
              f"{max(m['hourly']['wind_gusts_10m']):.0f} mph")
    except Exception as e:
        print(f"  Forecast unavailable right now ({type(e).__name__})")

    state_file = os.path.join(HERE, "out", "wind_state.json")
    try:
        state = json.load(open(state_file))
    except Exception:
        state = {"last_report": 0, "alerted": 0}
    now = time.time()
    if now - state["last_report"] >= 14 * 60:
        print("REPORT DUE")
        state["last_report"] = now
    if top > a.limit and top >= state["alerted"] + 5:
        print(f"WIND ALERT: {top} mph observed near home (limit {a.limit:.0f})")
        state["alerted"] = top
    os.makedirs(os.path.dirname(state_file), exist_ok=True)
    json.dump(state, open(state_file, "w"))


if __name__ == "__main__":
    main()
