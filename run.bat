@echo off
REM Launch the weather app on localhost so geolocation works.
echo Starting weather app at http://localhost:8731/index.html
start "" "http://localhost:8731/index.html"
python -m http.server 8731
