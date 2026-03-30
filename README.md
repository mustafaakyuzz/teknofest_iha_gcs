### Çalıştırma Komutları

cd ~/PX4-Autopilot && make px4_sitl gz_rc_cessna

MicroXRCEAgent udp4 -p 8888

cd ~/teknofest_iha && python3.11 api/mock_sunucu.py

cd ~/teknofest_iha && python3 algi/kamera_bridge.py

cd ~/teknofest_iha && python3 algi/yolo_tespit.py

cd ~/teknofest_iha && python3.11 algi/kilitlenme_algo.py

python3.11 ~/teknofest_iha/sim/hedef_iha_coklu.py

python3.11 ~/teknofest_iha/algi/intercept.py
