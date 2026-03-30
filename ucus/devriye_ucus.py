"""
ucus/devriye_ucus.py — Şartname uyumlu devriye + kilitlenme entegrasyonu

Şartname maddeleri:
- Kilitlenme sırasında otonom modda kalınmalı
- Tespit varsa hız azalt (hedefi daha uzun süre kamerada tut)
- Kilitlenme başarısında 10s bekle, devam et
- Müsabaka süresinin %75'i otonom olmalı (PX4 mission modu = otonom)
- Servo hareketi: sabit kanat için yaw/pitch ayarı PX4 mission modu içinde yapılır
"""
import asyncio, sys, os, threading, time
sys.path.insert(0, os.path.expanduser("~/teknofest_iha"))
import requests
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

SUNUCU_URL = "http://localhost:5000"

# PX4 SITL origin: 47.397971, 8.546164
DEVRIYE_WAYPOINTS = [
    (47.3987, 8.5455, 60.0),
    (47.3987, 8.5469, 60.0),
    (47.3975, 8.5469, 60.0),
    (47.3975, 8.5455, 60.0),
    (47.3975, 8.5441, 60.0),
    (47.3987, 8.5441, 60.0),
    (47.3987, 8.5455, 60.0),
]

HIZ_NORMAL          = 10.0   # m/s — normal devriye
HIZ_TESPIT          = 5.0    # m/s — tespit varken yavaşla (kamerada daha uzun tut)
HIZ_KILITLENME      = 3.0    # m/s — aktif kilitlenme sırasında çok yavaş
KALKIS_IRTIFA       = 30.0   # m
DEVRIYE_TEKRAR      = 20
KILITLENME_BEKLEME  = 10.0   # s — başarılı kilitlenme sonrası bekleme
ACCEPTANCE_RADIUS   = 15.0   # m — waypoint kabul yarıçapı

durum = {
    "tespit_var":          False,
    "kilitlenme_hazir":    False,
    "kilitlenme_aktif":    False,   # şu an sayıyor
    "kilitlenme_basarili": False,
    "otonom_mod":          True,
}
durum_lock = threading.Lock()


def polling():
    """Mock sunucudan tespit ve kilitlenme durumunu al."""
    while True:
        try:
            r = requests.get(f"{SUNUCU_URL}/api/tespit_durum", timeout=0.3)
            if r.ok:
                d = r.json()
                with durum_lock:
                    durum["tespit_var"]       = d.get("var", False)
                    durum["kilitlenme_hazir"] = d.get("kilitlenme_hazir", False)

            r2 = requests.get(f"{SUNUCU_URL}/api/kilitlenme_durum", timeout=0.3)
            if r2.ok:
                d2 = r2.json()
                with durum_lock:
                    durum["kilitlenme_aktif"] = d2.get("aktif", False)
                    if d2.get("basarili"):
                        durum["kilitlenme_basarili"] = True
        except Exception:
            pass
        time.sleep(0.1)


def hiz_al():
    """Duruma göre hız seç."""
    with durum_lock:
        if durum["kilitlenme_aktif"]:
            return HIZ_KILITLENME   # Sayaç çalışıyor — çok yavaş
        elif durum["tespit_var"]:
            return HIZ_TESPIT       # Tespit var — yavaşla
        else:
            return HIZ_NORMAL       # Normal devriye


def wp_item(enlem, boylam, irtifa, hiz):
    return MissionItem(
        latitude_deg=enlem, longitude_deg=boylam,
        relative_altitude_m=irtifa, speed_m_s=hiz,
        is_fly_through=True,
        gimbal_pitch_deg=float('nan'), gimbal_yaw_deg=float('nan'),
        camera_action=MissionItem.CameraAction.NONE,
        loiter_time_s=float('nan'),
        camera_photo_interval_s=float('nan'),
        acceptance_radius_m=ACCEPTANCE_RADIUS,
        yaw_deg=float('nan'),
        camera_photo_distance_m=float('nan'),
        vehicle_action=MissionItem.VehicleAction.NONE,
    )


async def misyon_yukle_baslat(drone, hiz):
    """Tüm waypoint'leri yükle ve misyonu başlat."""
    items = [wp_item(e, b, i, hiz) for e, b, i in DEVRIYE_WAYPOINTS]
    await drone.mission.set_return_to_launch_after_mission(False)
    await drone.mission.upload_mission(MissionPlan(items))
    await drone.mission.start_mission()
    with durum_lock:
        durum["otonom_mod"] = True


async def misyon_bitti_mi(drone) -> bool:
    """Mission tamamlandı mı kontrol et."""
    async for prog in drone.mission.mission_progress():
        return prog.current >= prog.total
    return False


async def devriye_ucus():
    drone = System()
    print("[DEVRIYE] Bağlanılıyor...")
    await drone.connect(system_address="udpin://0.0.0.0:14540")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("[DEVRIYE] Bağlandı!")
            break

    print("[DEVRIYE] GPS bekleniyor...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("[DEVRIYE] GPS hazır!")
            break

    # Polling thread başlat
    threading.Thread(target=polling, daemon=True).start()

    # Kalkış
    await drone.action.arm()
    print("[DEVRIYE] Kalkış...")
    await drone.action.takeoff()

    async for pos in drone.telemetry.position():
        if pos.relative_altitude_m >= KALKIS_IRTIFA * 0.85:
            print(f"[DEVRIYE] {pos.relative_altitude_m:.1f}m — devriye başlıyor")
            break
        print(f"[DEVRIYE] Yükseliyor:{pos.relative_altitude_m:.1f}m", end="\r")

    # ── Ana devriye döngüsü ─────────────────────────────────────────
    for tur in range(DEVRIYE_TEKRAR):
        print(f"\n[DEVRIYE] ═══ Tur {tur+1}/{DEVRIYE_TEKRAR} ═══")

        # Misyonu yükle ve başlat
        await misyon_yukle_baslat(drone, hiz_al())

        # Mission izleme döngüsü
        son_hiz_guncelleme = time.time()
        while True:
            await asyncio.sleep(0.3)

            # Durumu oku
            with durum_lock:
                tv  = durum["tespit_var"]
                kh  = durum["kilitlenme_hazir"]
                ka  = durum["kilitlenme_aktif"]
                kb  = durum["kilitlenme_basarili"]

            # Mevcut progress
            prog_current = prog_total = 0
            async for prog in drone.mission.mission_progress():
                prog_current = prog.current
                prog_total   = prog.total
                break

            mevcut_hiz = hiz_al()
            print(f"[DEVRIYE] WP:{prog_current}/{prog_total} | "
                  f"Hız:{mevcut_hiz:.0f}m/s | "
                  f"Tespit:{'✓' if tv else '✗'} | "
                  f"KilitHazır:{'✓' if kh else '✗'} | "
                  f"KilitAktif:{'✓' if ka else '✗'}",
                  end="\r")

            # ── Hız değişikliği gerekiyor mu? ──────────────────────
            # Her 2 saniyede bir veya durum değişince misyonu güncelle
            if time.time() - son_hiz_guncelleme > 2.0:
                await misyon_yukle_baslat(drone, mevcut_hiz)
                son_hiz_guncelleme = time.time()

            # ── Kilitlenme başarılı ─────────────────────────────────
            if kb:
                print(f"\n[DEVRIYE] *** KİLİTLENME BAŞARILI *** — "
                      f"{KILITLENME_BEKLEME}s bekleniyor...")
                with durum_lock:
                    durum["kilitlenme_basarili"] = False
                    durum["kilitlenme_aktif"]    = False
                    durum["tespit_var"]          = False
                # Kilitlenme sonrası normal hızda devam
                await misyon_yukle_baslat(drone, HIZ_NORMAL)
                son_hiz_guncelleme = time.time()
                await asyncio.sleep(KILITLENME_BEKLEME)

            # ── Mission bitti mi? ────────────────────────────────────
            if prog_current >= prog_total and prog_total > 0:
                print(f"\n[DEVRIYE] Tur {tur+1} tamamlandı")
                break

    # ── RTL ────────────────────────────────────────────────────────
    print("\n[DEVRIYE] Görev tamamlandı — RTL...")
    await drone.action.return_to_launch()

    async for pos in drone.telemetry.position():
        if pos.relative_altitude_m < 1.0:
            print("[DEVRIYE] İniş tamamlandı!")
            break
        print(f"[DEVRIYE] İniyor:{pos.relative_altitude_m:.1f}m", end="\r")


if __name__ == "__main__":
    print("=" * 55)
    print(f"TEKNOFEST — Devriye (Şartname Uyumlu)")
    print(f"Hızlar: Normal:{HIZ_NORMAL} | Tespit:{HIZ_TESPIT} | Kilit:{HIZ_KILITLENME} m/s")
    print(f"Kilitlenme bekleme: {KILITLENME_BEKLEME}s")
    print("=" * 55)
    try:
        asyncio.run(devriye_ucus())
    except KeyboardInterrupt:
        print("\n[DEVRIYE] Durduruldu.")