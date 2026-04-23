#!/bin/bash
# Tüm hataları tek seferde düzelt

# ── 1. yolo_tespit.py — Kalman float hatası ────────────────────────
sed -i 's/return float(durum\[0\]), float(durum\[1\]), float(durum\[2\]), float(durum\[3\])/return float(durum[0][0]), float(durum[1][0]), float(durum[2][0]), float(durum[3][0])/' \
    ~/teknofest_iha/algi/yolo_tespit.py

# ── 2. intercept.py — ground_speed_ned → velocity_ned ──────────────
sed -i 's/drone.telemetry.ground_speed_ned()/drone.telemetry.velocity_ned()/' \
    ~/teknofest_iha/algi/intercept.py
sed -i 's/vel.velocity_north_m_s\*\*2 +/vel.north_m_s**2 +/' \
    ~/teknofest_iha/algi/intercept.py
sed -i 's/vel.velocity_east_m_s\*\*2/vel.east_m_s**2/' \
    ~/teknofest_iha/algi/intercept.py

# ── 3. kilitlenme_algo.py — toleransı artır 1.0 → 1.5s ─────────────
sed -i 's/TOLERANS_SURE    = 1.0/TOLERANS_SURE    = 1.5/' \
    ~/teknofest_iha/algi/kilitlenme_algo.py

echo "Kontrol:"
echo "--- yolo_tespit.py kalman ---"
grep "float(durum" ~/teknofest_iha/algi/yolo_tespit.py | head -2

echo "--- intercept.py hiz ---"
grep "velocity_ned\|north_m_s\|east_m_s" ~/teknofest_iha/algi/intercept.py | head -4

echo "--- kilitlenme tolerans ---"
grep "TOLERANS_SURE" ~/teknofest_iha/algi/kilitlenme_algo.py | head -2
