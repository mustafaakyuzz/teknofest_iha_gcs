#!/bin/bash
# TEKNOFEST 2026 — Tam Sistem Başlatıcı
# Kullanım: bash baslat.sh

PROJE=~/teknofest_iha
PX4=~/PX4-Autopilot

# Renk kodları
YESIL='\033[0;32m'
SARI='\033[1;33m'
KIRMIZI='\033[0;31m'
SIFIR='\033[0m'

log() { echo -e "${YESIL}[BASLAT]${SIFIR} $1"; }
warn() { echo -e "${SARI}[UYARI]${SIFIR} $1"; }

# Eski processleri temizle
log "Eski processler temizleniyor..."
pkill -f "px4" 2>/dev/null
pkill -f "MicroXRCEAgent" 2>/dev/null
pkill -f "mock_sunucu" 2>/dev/null
pkill -f "telemetri_dongusu" 2>/dev/null
pkill -f "kamera_bridge" 2>/dev/null
pkill -f "hedef_iha" 2>/dev/null
pkill -f "yolo_tespit" 2>/dev/null
pkill -f "kilitlenme_algo" 2>/dev/null
pkill -f "intercept" 2>/dev/null
sleep 2

log "Gnome-terminal ile sekmeler açılıyor..."

# T1 — PX4 SITL + Gazebo
gnome-terminal --tab --title="T1-PX4" -- bash -c "
  echo '=== T1: PX4 SITL ===' 
  cd $PX4 && make px4_sitl gz_rc_cessna
  bash" &
sleep 1

# T2 — MicroXRCE (PX4 açıldıktan 15s sonra)
gnome-terminal --tab --title="T2-XRCE" -- bash -c "
  echo '=== T2: MicroXRCE Agent ===' 
  sleep 15
  MicroXRCEAgent udp4 -p 8888
  bash" &

# T3 — Mock Sunucu
gnome-terminal --tab --title="T3-API" -- bash -c "
  echo '=== T3: Mock Sunucu ===' 
  sleep 5
  cd $PROJE && python3.11 api/mock_sunucu.py
  bash" &

# T4 — Telemetri
gnome-terminal --tab --title="T4-TELEM" -- bash -c "
  echo '=== T4: Telemetri ===' 
  sleep 20
  cd $PROJE && echo "Telemetri intercept icinde"
  bash" &

# T5 — Kamera Bridge
gnome-terminal --tab --title="T5-CAM" -- bash -c "
  echo '=== T5: Kamera Bridge ===' 
  sleep 20
  cd $PROJE && python3 algi/kamera_bridge.py
  bash" &

# T6 — Hedef IHA'lar (Gazebo açıldıktan sonra)
#gnome-terminal --tab --title="T6-HEDEF" -- bash -c "
 # echo '=== T6: Hedef IHA Coklu ===' 
  #sleep 30
  #cd $PROJE && python3 sim/hedef_iha_coklu.py
  #bash" &

# T7 — Tespit
#gnome-terminal --tab --title="T7-TESPIT" -- bash -c "
 # echo '=== T7: Tespit ===' 
  #sleep 25
  #cd $PROJE && python3.11 algi/yolo_tespit.py
  #bash" &

# T8 — Kilitlenme
#gnome-terminal --tab --title="T8-KILIT" -- bash -c "
 # echo '=== T8: Kilitlenme Algo ===' 
  #sleep 25
  #cd $PROJE && python3.11 algi/kilitlenme_algo.py
  #bash" &

# T9 — Intercept + Uçuş (en son)
gnome-terminal --tab --title="T9-UCUS" -- bash -c "
  echo '=== T9: Intercept + Ucus ===' 
  sleep 35
  cd $PROJE && python3.11 algi/intercept.py
  bash" &

echo ""
echo -e "${YESIL}════════════════════════════════════════${SIFIR}"
echo -e "${YESIL}  TEKNOFEST 2026 — Sistem Başlatılıyor  ${SIFIR}"
echo -e "${YESIL}════════════════════════════════════════${SIFIR}"
echo ""
echo -e "  T1  PX4 SITL          → hemen"
echo -e "  T2  MicroXRCE         → 15s sonra"
echo -e "  T3  Mock Sunucu       → 5s sonra"
echo -e "  T4  Telemetri         → 20s sonra"
echo -e "  T5  Kamera Bridge     → 20s sonra"
echo -e "  T6  Hedef IHA'lar     → 30s sonra"
echo -e "  T7  Tespit            → 25s sonra"
echo -e "  T8  Kilitlenme        → 25s sonra"
echo -e "  T9  Intercept+Uçuş   → 35s sonra"
echo ""
echo -e "${SARI}  Tarayıcı: http://localhost:8554/gcs_sim.html${SIFIR}"
echo ""