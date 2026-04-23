#!/bin/bash

# 1. Kilitlenme toleransını 3s yap
sed -i 's/TOLERANS_SURE    = 1.5/TOLERANS_SURE    = 3.0/' \
    ~/teknofest_iha/algi/kilitlenme_algo.py

# 2. Kalman dt'yi artır — bbox daha fazla öne gitsin
sed -i 's/def one_al(self, cx, cy, vx, vy, dt=0.05):/def one_al(self, cx, cy, vx, vy, dt=0.15):/' \
    ~/teknofest_iha/algi/yolo_tespit.py

# 3. Kalman kayıp limitini artır — daha uzun tahmin yapsın
sed -i 's/KALMAN_KAYIP_LIMIT = 8/KALMAN_KAYIP_LIMIT = 30/' \
    ~/teknofest_iha/algi/yolo_tespit.py

# 4. Kalman tahmini sırasında da kilitlenme_hazir True yap
# (şu an kalman_tahmin ise kilit=False yapıyor — bunu kaldır)
sed -i 's/    if kalman_tahmin:/    if False:  # kalman_tahmin kontrolü kaldırıldı/' \
    ~/teknofest_iha/algi/yolo_tespit.py

echo "Kontrol:"
grep "TOLERANS_SURE\|KALMAN_KAYIP\|kalman_tahmin\|dt=0\." ~/teknofest_iha/algi/kilitlenme_algo.py | head -3
grep "KALMAN_KAYIP\|dt=0\.\|kalman_tahmin\|False:" ~/teknofest_iha/algi/yolo_tespit.py | head -6
