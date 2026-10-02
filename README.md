# Weather

A single-file weather app powered by [Open-Meteo](https://open-meteo.com) — free, open data, **no API key required**.

## Run it

**Quickest:** double-click `index.html` to open it in your browser. City search works right away.

**With geolocation (📍 My location):** browsers only allow location access over `http://localhost` or `https://`, not raw `file://`. To enable it, serve the folder locally:

```sh
# from this folder
python -m http.server 8731
```

Then open **http://localhost:8731/index.html**

## Features

- Current conditions — temperature, feels-like, wind, humidity, precipitation, today's high/low
- Next 24 hours (scrollable) and a 7-day forecast
- City search with live autocomplete
- Auto-detect location (geolocation, with IP fallback)
- °F / °C toggle and dark / light mode (both remembered)
- Weather icons via WMO weather codes

## How it works

Pure HTML/CSS/JS in one file — no build step, no dependencies. It calls two Open-Meteo endpoints:

- **Geocoding** — `geocoding-api.open-meteo.com` to turn a city name (or coordinates) into a location
- **Forecast** — `api.open-meteo.com` for current, hourly, and daily data

## Data

Weather data by [Open-Meteo.com](https://open-meteo.com), licensed CC BY 4.0.
