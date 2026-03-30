"""
algi/intercept.py
Tespit edilen hedefin piksel konumundan tahmini GPS konumu hesapla,
ana uçağı hedefe doğru yönelt (mission waypoint güncelle).

Çalışma prensibi:
1. yolo_tespit.py hedefi tespit eder → piksel merkezi (cx, cy)
2. Piksel sapmasından açısal sapma hesapla (kamera FoV)
3. Ana uçağın GPS + yaw + açısal sapma → hedefin tahmini GPS
4. Bu GPS'e yeni mission waypoint gönder
5. Boyut %6'ya ulaşınca intercept durur, kilitlenme başlar
"""
import asyncio, sys, os, math, time, threading
sys.path.insert(0, os.path.expanduser("~/teknofest_iha"))
import requests
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

SUNUCU_URL = "http://localhost:5000"

# Kamera parametreleri (rc_cessna SDF)
CAM_FOV_H   = 1.309   # 75° yatay FoV (radyan)
CAM_FOV_V   = 0.786   # ~45° dikey FoV (radyan) — 16:9 için
IMG_W       = 1280
IMG_H       = 720

# Intercept parametreleri
INTERCEPT_MESAFE   = 80.0    # m — hedefe bu kadar yaklaşmaya çalış
INTERCEPT_IRTIFA   = 60.0    # m — sabit irtifa
INTERCEPT_HIZ      = 15.0    # m/s — yaklaşma hızı
DEVRIYE_HIZ        = 10.0    # m/s — normal devriye
BOYUT_ESIK         = 0.06    # %6 — bu boyuta ulaşınca kilitlenme
BOYUT_YAKLASMA     = 0.02    # %2 — bu boyutta intercept başla
GUNCELLEME_ARALIK  = 1.0     # s — waypoint güncelleme sıklığı

# Devriye waypoint'leri
DEVRIYE_WP = [
    (47.3987, 8.5455, 60.0),
    (47.3987, 8.5469, 60.0),
    (47.3975, 8.5469, 60.0),
    (47.3975, 8.5455, 60.0),
    (47.3975, 8.5441, 60.0),
    (47.3987, 8.5441, 60.0),
]

# Paylaşımlı durum
durum = {
    "mod":          "devriye",   # devriye | intercept | kilitlenme
    "hedef_cx":     0.5,
    "hedef_cy":     0.5,
    "hedef_boyut":  0.0,
    "tespit_var":   False,
    "kilit_basarili": False,
    "iha_lat":      47.3979,
    "iha_lon":      8.5461,
    "iha_alt":      60.0,
    "iha_yaw":      0.0,         # derece
}
durum_lock = threading.Lock()


def tespit_polling():
    """yolo_tespit.py'den tespit durumunu al."""
    while True:
        try:
            r = requests.get(f"{SUNUCU_URL}/api/tespit_durum", timeout=0.3)
            if r.ok:
                d = r.json()
                with durum_lock:
                    durum["tespit_var"]  = d.get("var", False)
                    durum["hedef_cx"]    = d.get("cx", 0.5)
                    durum["hedef_cy"]    = d.get("cy", 0.5)
                    w = d.get("w", 0)
                    h = d.get("h", 0)
                    durum["hedef_boyut"] = max(w, h)

            r2 = requests.get(f"{SUNUCU_URL}/api/kilitlenme_durum", timeout=0.3)
            if r2.ok:
                d2 = r2.json()
                if d2.get("basarili"):
                    with durum_lock:
                        durum["kilit_basarili"] = True
        except Exception:
            pass
        time.sleep(0.1)


def piksel_to_aci(cx_norm: float, cy_norm: float):
    """
    Normalize piksel konumunu (0-1) açısal sapmaya çevir.
    cx=0.5 → merkez (0 sapma)
    cx=0   → sol kenar (-FoV/2)
    cx=1   → sağ kenar (+FoV/2)
    Returns: (yaw_sapma_rad, pitch_sapma_rad)
    """
    yaw_sapma   = (cx_norm - 0.5) * CAM_FOV_H
    pitch_sapma = (0.5 - cy_norm) * CAM_FOV_V
    return yaw_sapma, pitch_sapma


def hedef_gps_hesapla(iha_lat, iha_lon, iha_alt, iha_yaw_deg,
                       cx_norm, cy_norm, mesafe=INTERCEPT_MESAFE):
    """
    Kameradaki piksel konumundan hedefin tahmini GPS'ini hesapla.
    iha_yaw_deg: uçağın yönü (derece, kuzey=0)
    """
    yaw_sapma, pitch_sapma = piksel_to_aci(cx_norm, cy_norm)

    # Uçağın yön açısı + piksel sapması = hedef yönü
    hedef_yon_rad = math.radians(iha_yaw_deg) + yaw_sapma

    # Yatay mesafe projeksiyon (pitch sapmasını da hesaba kat)
    yatay_mesafe = mesafe * math.cos(pitch_sapma)

    # GPS offset (basit düzlem yaklaşımı)
    # 1 derece enlem ≈ 111320m, boylam cos(lat) ile çarpılır
    delta_lat = yatay_mesafe * math.cos(hedef_yon_rad) / 111320.0
    delta_lon = yatay_mesafe * math.sin(hedef_yon_rad) / (111320.0 * math.cos(math.radians(iha_lat)))

    hedef_lat = iha_lat + delta_lat
    hedef_lon = iha_lon + delta_lon

    return hedef_lat, hedef_lon


def wp_item(lat, lon, alt, hiz, is_fly_through=True):
    return MissionItem(
        latitude_deg=lat, longitude_deg=lon,
        relative_altitude_m=alt, speed_m_s=hiz,
        is_fly_through=is_fly_through,
        gimbal_pitch_deg=float('nan'), gimbal_yaw_deg=float('nan'),
        camera_action=MissionItem.CameraAction.NONE,
        loiter_time_s=float('nan'),
        camera_photo_interval_s=float('nan'),
        acceptance_radius_m=10,
        yaw_deg=float('nan'),
        camera_photo_distance_m=float('nan'),
        vehicle_action=MissionItem.VehicleAction.NONE,
    )


async def telemetri_al(drone):
    """PX4'ten gerçek zamanlı telemetri al."""
    async for pos in drone.telemetry.position():
        with durum_lock:
            durum["iha_lat"] = pos.latitude_deg
            durum["iha_lon"] = pos.longitude_deg
            durum["iha_alt"] = pos.relative_altitude_m
        break

    async for att in drone.telemetry.heading():
        with durum_lock:
            durum["iha_yaw"] = att.heading_deg
        break


async def devriye_mission_yukle(drone, hiz=DEVRIYE_HIZ):
    items = [wp_item(lat, lon, alt, hiz) for lat, lon, alt in DEVRIYE_WP]
    await drone.mission.set_return_to_launch_after_mission(False)
    await drone.mission.upload_mission(MissionPlan(items))
    await drone.mission.start_mission()


async def intercept_mission_yukle(drone, hedef_lat, hedef_lon):
    """Hedef konumuna tek waypoint gönder."""
    items = [wp_item(hedef_lat, hedef_lon, INTERCEPT_IRTIFA, INTERCEPT_HIZ, is_fly_through=False)]
    await drone.mission.set_return_to_launch_after_mission(False)
    await drone.mission.upload_mission(MissionPlan(items))
    await drone.mission.start_mission()


async def ana_dongu(drone):
    son_guncelleme  = 0
    son_mod         = "devriye"
    kilitlenme_bekleme = False

    await devriye_mission_yukle(drone)
    print("[INTERCEPT] Devriye başladı")

    while True:
        await asyncio.sleep(0.2)

        # Telemetriyi güncelle
        try:
            await telemetri_al(drone)
        except Exception:
            pass

        with durum_lock:
            mod          = durum["mod"]
            tespit       = durum["tespit_var"]
            boyut        = durum["hedef_boyut"]
            cx           = durum["hedef_cx"]
            cy           = durum["hedef_cy"]
            kb           = durum["kilit_basarili"]
            iha_lat      = durum["iha_lat"]
            iha_lon      = durum["iha_lon"]
            iha_alt      = durum["iha_alt"]
            iha_yaw      = durum["iha_yaw"]

        # ── Kilitlenme başarılı ─────────────────────────────────────
        if kb:
            print("\n[INTERCEPT] *** KİLİTLENME BAŞARILI *** — Devriyeye dönülüyor")
            with durum_lock:
                durum["kilit_basarili"] = False
                durum["mod"]            = "devriye"
            await asyncio.sleep(10.0)
            await devriye_mission_yukle(drone)
            son_mod = "devriye"
            continue

        # ── Mod belirleme ───────────────────────────────────────────
        if not tespit or boyut < BOYUT_YAKLASMA:
            yeni_mod = "devriye"
        elif boyut >= BOYUT_ESIK:
            yeni_mod = "kilitlenme"  # Yeterince büyük — kilitlenme algo devreye girer
        else:
            yeni_mod = "intercept"   # Tespit var ama küçük — yaklaş

        with durum_lock:
            durum["mod"] = yeni_mod

        # ── Mod değişikliği ─────────────────────────────────────────
        if yeni_mod != son_mod:
            print(f"\n[INTERCEPT] Mod: {son_mod} → {yeni_mod} | "
                  f"Boyut:{boyut*100:.1f}% | "
                  f"{'Tespit' if tespit else 'Tespit yok'}")
            if yeni_mod == "devriye":
                await devriye_mission_yukle(drone)
            son_mod = yeni_mod

        # ── Intercept modu — waypoint güncelle ─────────────────────
        if yeni_mod == "intercept" and time.time() - son_guncelleme > GUNCELLEME_ARALIK:
            hedef_lat, hedef_lon = hedef_gps_hesapla(
                iha_lat, iha_lon, iha_alt, iha_yaw, cx, cy,
                mesafe=INTERCEPT_MESAFE
            )
            await intercept_mission_yukle(drone, hedef_lat, hedef_lon)
            son_guncelleme = time.time()
            print(f"[INTERCEPT] Yaklaşıyor | "
                  f"Boyut:{boyut*100:.1f}% → hedef:{hedef_lat:.5f},{hedef_lon:.5f} | "
                  f"IHA yaw:{iha_yaw:.0f}°", end="\r")

        # ── Kilitlenme modu — sadece logla ─────────────────────────
        elif yeni_mod == "kilitlenme":
            print(f"[INTERCEPT] KİLİTLENME BÖLGEYE GİRDİ | "
                  f"Boyut:{boyut*100:.1f}% ≥ %{BOYUT_ESIK*100:.0f}", end="\r")


async def main():
    drone = System()
    print("[INTERCEPT] Bağlanılıyor...")
    await drone.connect(system_address="udpin://0.0.0.0:14540")

    async for state in drone.core.connection_state():
        if state.is_connected:
            print("[INTERCEPT] Bağlandı!")
            break

    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("[INTERCEPT] GPS hazır!")
            break

    await drone.action.arm()
    await drone.action.takeoff()
    print("[INTERCEPT] Kalkış...")

    async for pos in drone.telemetry.position():
        if pos.relative_altitude_m >= 25:
            print(f"[INTERCEPT] {pos.relative_altitude_m:.0f}m — başlıyor")
            break
        print(f"[INTERCEPT] Yükseliyor: {pos.relative_altitude_m:.0f}m", end="\r")

    threading.Thread(target=tespit_polling, daemon=True).start()
    await ana_dongu(drone)


if __name__ == "__main__":
    print("=" * 55)
    print("  TEKNOFEST — Intercept + Kilitlenme")
    print(f"  Yaklaşma: {INTERCEPT_HIZ}m/s | Eşik: %{BOYUT_ESIK*100:.0f}")
    print("=" * 55)
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INTERCEPT] Durduruldu.")