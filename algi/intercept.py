"""
algi/intercept.py — Final (Simetri Kırıcı & Kusursuz Yay)
- Simetri Kilitlenmesi (Merkezden geçiş) sorunu çözüldü.
- Sonsuz MAVSDK yükleme hatası Hash kontrolü ile engellendi.
"""
import asyncio, sys, os, math, time, threading, json
sys.path.insert(0, os.path.expanduser("~/teknofest_iha"))
import requests
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

SUNUCU_URL    = "http://localhost:5000"
TAKIM_NO      = 1

CAM_FOV_H = 1.309
CAM_FOV_V = 0.736

INTERCEPT_IRTIFA  = 25.0
INTERCEPT_HIZ     = 18.0
DEVRIYE_HIZ       = 12.0
BOYUT_ESIK        = 0.06
BOYUT_YAKLASMA    = 0.005
GUNCELLEME_ARALIK = 0.5
MESAFE_MIN        = 20.0
MESAFE_MAX        = 150.0

DEVRIYE_WP = [
    (47.3985, 8.5461, 25.0),
    (47.3985, 8.5488, 25.0),
    (47.3973, 8.5488, 25.0),
    (47.3973, 8.5434, 25.0),
    (47.3985, 8.5434, 25.0),
]

durum = {
    "mod": "devriye",
    "hss_listesi": [], 
    "hedef_cx": 0.5, "hedef_cy": 0.5,
    "hedef_boyut": 0.0, "hedef_w": 0.0, "hedef_h": 0.0,
    "hedef_bx1": 0, "hedef_by1": 0, "hedef_bx2": 0, "hedef_by2": 0,
    "tespit_var": False, "av_icinde": False,
    "kilit_basarili": False, "kilit_aktif": False,
    "iha_lat": 0.0, "iha_lon": 0.0,
    "iha_alt": 30.0, "iha_yaw": 0.0,
    "iha_hiz": 0.0, "iha_pitch": 0.0, "iha_roll": 0.0,
    "iha_batarya": 80.0,
    "aktif_wp_index": 0,
}
durum_lock = threading.Lock()

# ── Polling thread ──────────────────────────────────────────────────
def tespit_polling():
    while True:
        try:
            r = requests.get(f"{SUNUCU_URL}/api/tespit_durum", timeout=0.3)
            if r.ok:
                d = r.json()
                with durum_lock:
                    durum["tespit_var"]  = d.get("var", False)
                    durum["hedef_cx"]    = d.get("cx", 0.5)
                    durum["hedef_cy"]    = d.get("cy", 0.5)
                    w = d.get("w", 0); h = d.get("h", 0)
                    durum["hedef_w"]     = w
                    durum["hedef_h"]     = h
                    durum["hedef_boyut"] = max(w, h)
                    durum["av_icinde"]   = d.get("av_icinde", False)
                    durum["hedef_bx1"]   = d.get("bx1", 0)
                    durum["hedef_by1"]   = d.get("by1", 0)
                    durum["hedef_bx2"]   = d.get("bx2", 0)
                    durum["hedef_by2"]   = d.get("by2", 0)

            r2 = requests.get(f"{SUNUCU_URL}/api/kilitlenme_durum", timeout=0.3)
            if r2.ok:
                d2 = r2.json()
                with durum_lock:
                    durum["kilit_basarili"] = d2.get("basarili", False)
                    durum["kilit_aktif"]    = d2.get("aktif", False)

            r3 = requests.get(f"{SUNUCU_URL}/api/hss_koordinatlari", timeout=0.3)
            if r3.ok:
                d3 = r3.json()
                with durum_lock:
                    durum["hss_listesi"] = d3.get("hss_koordinat_bilgileri", [])
        except Exception:
            pass
        time.sleep(0.5) 

# ── Telemetri gönder ───────────────────────────────────────────────
def telemetri_gonder_thread():
    try:
        requests.post(f"{SUNUCU_URL}/api/giris", json={"kadi": "takim", "sifre": "sifre"}, timeout=2)
    except Exception: pass

    while True:
        try:
            with durum_lock:
                lat, lon, alt = durum["iha_lat"], durum["iha_lon"], durum["iha_alt"]
                yaw, hiz, pitch = durum["iha_yaw"], durum["iha_hiz"], durum["iha_pitch"]
                roll, bat, ka = durum["iha_roll"], durum["iha_batarya"], durum["kilit_aktif"]
                cx, cy, bw, bh = durum["hedef_cx"], durum["hedef_cy"], durum["hedef_w"], durum["hedef_h"]

            now = time.gmtime()
            paket = {
                "takim_numarasi":   TAKIM_NO,
                "iha_enlem":        round(lat, 6),
                "iha_boylam":       round(lon, 6),
                "iha_irtifa":       round(alt, 2),
                "iha_dikilme":      round(pitch, 2),
                "iha_yonelme":      round(yaw, 1),
                "iha_yatis":        round(roll, 2),
                "iha_hiz":          round(hiz, 2),
                "iha_batarya":      round(bat, 1),
                "iha_otonom":       1,
                "iha_kilitlenme":   1 if ka else 0,
                "hedef_merkez_X":   round(cx * 1280),
                "hedef_merkez_Y":   round(cy * 720),
                "hedef_genislik":   round(bw * 1280),
                "hedef_yukseklik":  round(bh * 720),
                "gps_saati": {"saat": now.tm_hour, "dakika": now.tm_min, "saniye": now.tm_sec, "milisaniye": 0},
            }
            requests.post(f"{SUNUCU_URL}/api/telemetri_gonder", json=paket, timeout=0.5)
        except Exception: pass
        time.sleep(1.0)

# ── Yardımcı Fonksiyonlar ──────────────────────────────────────────
def boyut_to_mesafe(b):
    if b <= 0: return MESAFE_MAX
    oran = (b - 0.005) / (0.20 - 0.005)
    return max(MESAFE_MIN, min(MESAFE_MAX, MESAFE_MAX - oran*(MESAFE_MAX-MESAFE_MIN)))

def en_yakin_wp_index(lat, lon, wp_listesi, limit_len):
    if not wp_listesi or limit_len == 0: return 0
    if lat == 0.0 and lon == 0.0: return 0 

    min_dist = float('inf')
    idx = 0
    limit = min(len(wp_listesi), limit_len) 
    for i in range(limit):
        w_lat, w_lon, _ = wp_listesi[i]
        dist = math.hypot(lat - w_lat, lon - w_lon)
        if dist < min_dist:
            min_dist = dist
            idx = i
            
    return min(idx + 1, len(wp_listesi) - 1)

# YENİ: Sonsuz döngüden kurtulmak için Hash kontrolü
def get_hss_hash(hss_list):
    s_list = sorted(hss_list, key=lambda x: x.get("id", 0))
    return str([(h.get("id"), h.get("hssYaricap")) for h in s_list])

def arc_rotasi_olustur(ham_wp_listesi, hss_listesi, alt, kapali_dongu=True):
    R_EARTH = 111320.0
    GUVENLIK_MARJI = 30.0  
    
    sik_noktalar = []
    baslangic = 0 if kapali_dongu else 1
    
    for i in range(baslangic, len(ham_wp_listesi)):
        p1 = ham_wp_listesi[i-1]
        p2 = ham_wp_listesi[i]

        path_dx = (p2[1] - p1[1]) * R_EARTH * math.cos(math.radians(p1[0]))
        path_dy = (p2[0] - p1[0]) * R_EARTH
        path_len = math.hypot(path_dx, path_dy)
        
        # Orijinal hattın dik (normal) vektörü
        nx = -path_dy / path_len if path_len > 0 else 0
        ny = path_dx / path_len if path_len > 0 else 0

        adim_sayisi = max(1, int(path_len / 8.0))
        for j in range(adim_sayisi):
            t = j / adim_sayisi
            lat = p1[0] + t * (p2[0] - p1[0])
            lon = p1[1] + t * (p2[1] - p1[1])
            
            g_lat, g_lon = lat, lon
            for hss in hss_listesi:
                h_lat = hss.get("hssEnlem", 0)
                h_lon = hss.get("hssBoylam", 0)
                yaricap = hss.get("hssYaricap", 0) + GUVENLIK_MARJI

                dx = (g_lon - h_lon) * R_EARTH * math.cos(math.radians(h_lat))
                dy = (g_lat - h_lat) * R_EARTH
                d_m = math.hypot(dx, dy)

                if d_m < yaricap:
                    # YENİ: SİMETRİ KIRICI (Merkezden geçen rotalar için yanal itme)
                    yanal = dx * nx + dy * ny
                    if abs(yanal) < 15.0:
                        yon = 1 if yanal >= 0 else -1
                        dx += nx * 15.0 * yon
                        dy += ny * 15.0 * yon
                        d_m = math.hypot(dx, dy)
                        
                    if d_m == 0: dx, dy, d_m = 1, 1, 1.414
                    itme = yaricap / d_m
                    g_lon = h_lon + (dx * itme) / (R_EARTH * math.cos(math.radians(h_lat)))
                    g_lat = h_lat + (dy * itme) / R_EARTH
                    
            sik_noktalar.append((g_lat, g_lon, alt))
            
    if not kapali_dongu:
        # Son noktanın güvenliği
        g_lat, g_lon = ham_wp_listesi[-1][0], ham_wp_listesi[-1][1]
        for hss in hss_listesi:
            h_lat = hss.get("hssEnlem", 0)
            h_lon = hss.get("hssBoylam", 0)
            yaricap = hss.get("hssYaricap", 0) + GUVENLIK_MARJI
            dx = (g_lon - h_lon) * R_EARTH * math.cos(math.radians(h_lat))
            dy = (g_lat - h_lat) * R_EARTH
            d_m = math.hypot(dx, dy)
            if d_m < yaricap:
                yanal = dx * nx + dy * ny
                if abs(yanal) < 15.0:
                    yon = 1 if yanal >= 0 else -1
                    dx += nx * 15.0 * yon
                    dy += ny * 15.0 * yon
                    d_m = math.hypot(dx, dy)
                if d_m == 0: dx, dy, d_m = 1, 1, 1.414
                itme = yaricap / d_m
                g_lon = h_lon + (dx * itme) / (R_EARTH * math.cos(math.radians(h_lat)))
                g_lat = h_lat + (dy * itme) / R_EARTH
        sik_noktalar.append((g_lat, g_lon, alt))

    guvenli_noktalar = []
    # Üst üste binen çok yakın noktaları MAVSDK yorulmasın diye filtreliyoruz
    for g_lat, g_lon, a in sik_noktalar:
        if not guvenli_noktalar:
            guvenli_noktalar.append((g_lat, g_lon, a))
        else:
            son_lat, son_lon, _ = guvenli_noktalar[-1]
            dx2 = (g_lon - son_lon) * R_EARTH * math.cos(math.radians(g_lat))
            dy2 = (g_lat - son_lat) * R_EARTH
            if math.hypot(dx2, dy2) > 6.0: 
                guvenli_noktalar.append((g_lat, g_lon, a))

    return guvenli_noktalar

def hedef_gps(iha_lat, iha_lon, iha_alt, iha_yaw_deg, cx, cy, boyut):
    yaw_s  = (cx - 0.5) * CAM_FOV_H
    pit_s  = (0.5 - cy) * CAM_FOV_V
    yon    = math.radians(iha_yaw_deg) + yaw_s
    mesafe = boyut_to_mesafe(boyut)
    yatay  = mesafe * math.cos(max(-1.4, min(1.4, pit_s)))
    R_lat, R_lon  = 111320.0, 111320.0 * math.cos(math.radians(iha_lat))
    return (iha_lat + yatay * math.cos(yon) / R_lat, iha_lon + yatay * math.sin(yon) / R_lon)

def wp(lat, lon, alt, hiz, fly_through=True, r=5.0):
    return MissionItem(
        latitude_deg=lat, longitude_deg=lon, relative_altitude_m=float(alt), speed_m_s=float(hiz),
        is_fly_through=fly_through, gimbal_pitch_deg=float('nan'), gimbal_yaw_deg=float('nan'),
        camera_action=MissionItem.CameraAction.NONE, loiter_time_s=float('nan'), camera_photo_interval_s=float('nan'),
        acceptance_radius_m=r, yaw_deg=float('nan'), camera_photo_distance_m=float('nan'), vehicle_action=MissionItem.VehicleAction.NONE,
    )

async def misyon_yukle(drone, items, resume_idx=0):
    try:
        await drone.mission.pause_mission()
        await drone.mission.clear_mission()
    except Exception: pass
    
    try:
        await drone.mission.set_return_to_launch_after_mission(False)
        await drone.mission.upload_mission(MissionPlan(items))
        if 0 < resume_idx < len(items):
            await drone.mission.set_current_mission_item(resume_idx)
        await drone.mission.start_mission()
    except Exception as e:
        print(f"[HATA] MAVSDK Görev Yükleme: {e}")

# ── Telemetri Alma ──────────────────────────────────────────────────
async def telemetri_al(drone):
    async def gorev_takip():
        async for prog in drone.mission.mission_progress():
            with durum_lock: durum["aktif_wp_index"] = prog.current
    async def konum():
        async for pos in drone.telemetry.position():
            with durum_lock:
                durum["iha_lat"], durum["iha_lon"], durum["iha_alt"] = pos.latitude_deg, pos.longitude_deg, pos.relative_altitude_m
    async def yaw():
        async for att in drone.telemetry.heading():
            with durum_lock: durum["iha_yaw"] = att.heading_deg
    async def hiz():
        async for vel in drone.telemetry.velocity_ned():
            with durum_lock: durum["iha_hiz"] = math.sqrt(vel.north_m_s**2 + vel.east_m_s**2)
    async def attitude():
        async for att in drone.telemetry.attitude_euler():
            with durum_lock: durum["iha_pitch"], durum["iha_roll"] = att.pitch_deg, att.roll_deg

    for task in [konum, yaw, hiz, attitude, gorev_takip]: asyncio.create_task(task())

# ── Ana döngü ───────────────────────────────────────────────────────
async def ana_dongu(drone):
    son_mod, son_guncelleme, son_hss_durum = None, 0, [] 
    print("[INTERCEPT] Ana döngü başladı\n")
    try:
        guvenli_wp = arc_rotasi_olustur(DEVRIYE_WP, [], INTERCEPT_IRTIFA, True)
        UZUN_DEVRİYE = guvenli_wp * 2 
        await misyon_yukle(drone, [wp(lat, lon, alt, DEVRIYE_HIZ, True, 5) for lat, lon, alt in UZUN_DEVRİYE], 0)
        son_mod = "devriye"
    except Exception as e: print(f"[INTERCEPT] İlk misyon hatası: {e}")

    while True:
        await asyncio.sleep(0.15)
        with durum_lock:
            tespit, boyut = durum["tespit_var"], durum["hedef_boyut"]
            cx, cy = durum["hedef_cx"], durum["hedef_cy"]
            kb, ka = durum["kilit_basarili"], durum["kilit_aktif"]
            iha_lat, iha_lon, iha_alt, iha_yaw = durum["iha_lat"], durum["iha_lon"], durum["iha_alt"], durum["iha_yaw"]
            aktif_idx, hssler = durum["aktif_wp_index"], list(durum["hss_listesi"])

        if kb:
            print("\n[INTERCEPT] ★ KİLİTLENME BAŞARILI ★ — Devriyeye dön")
            with durum_lock: durum["kilit_basarili"], durum["mod"] = False, "devriye"
            await asyncio.sleep(5.0)
            try:
                guvenli_wp = arc_rotasi_olustur(DEVRIYE_WP, hssler, INTERCEPT_IRTIFA, True)
                UZUN_DEVRİYE = guvenli_wp * 2
                idx = en_yakin_wp_index(iha_lat, iha_lon, UZUN_DEVRİYE, len(guvenli_wp))
                await misyon_yukle(drone, [wp(lat, lon, alt, DEVRIYE_HIZ, True, 5) for lat, lon, alt in UZUN_DEVRİYE], idx)
                son_mod, son_hss_durum = "devriye", list(hssler)
            except Exception as e: print(f"[HATA] {e}")
            continue

        if ka:
            if son_mod != "kilitlenme":
                print(f"\n[INTERCEPT] Kilitlenme aktif | Boyut:{boyut*100:.1f}% — yavaş devriye")
                try:
                    guvenli_wp = arc_rotasi_olustur(DEVRIYE_WP, hssler, INTERCEPT_IRTIFA, True)
                    UZUN_DEVRİYE = guvenli_wp * 2
                    idx = en_yakin_wp_index(iha_lat, iha_lon, UZUN_DEVRİYE, len(guvenli_wp))
                    await misyon_yukle(drone, [wp(lat, lon, alt, 4.0, True, 5) for lat, lon, alt in UZUN_DEVRİYE], idx)
                    son_mod = "kilitlenme"
                except Exception as e: print(f"[HATA] {e}")
            with durum_lock: durum["mod"] = "kilitlenme"
            continue

        yeni_mod = "intercept" if (tespit and boyut >= BOYUT_YAKLASMA) else "devriye"
        with durum_lock: durum["mod"] = yeni_mod
        
        # YENİ: Sonsuz döngüden kurtaran kesin HASH kontrolü
        hss_degisti = (get_hss_hash(hssler) != get_hss_hash(son_hss_durum))

        if yeni_mod != son_mod or (yeni_mod == "devriye" and hss_degisti):
            if yeni_mod == "devriye":
                mesaj = "HSS DEĞİŞTİ! Simetri Kırıldı, Kavis Yayılıyor..." if hss_degisti else f"→ DEVRİYE | boyut:{boyut*100:.1f}%"
                print(f"\n[INTERCEPT] {mesaj}")
                try:
                    guvenli_wp = arc_rotasi_olustur(DEVRIYE_WP, hssler, INTERCEPT_IRTIFA, True)
                    UZUN_DEVRİYE = guvenli_wp * 2
                    idx = en_yakin_wp_index(iha_lat, iha_lon, UZUN_DEVRİYE, len(guvenli_wp))
                    await misyon_yukle(drone, [wp(lat, lon, alt, DEVRIYE_HIZ, True, 5) for lat, lon, alt in UZUN_DEVRİYE], idx)
                except Exception as e: print(f"[HATA] Rota hesaplama: {e}")
            else:
                print(f"\n[INTERCEPT] → INTERCEPT | boyut:{boyut*100:.1f}%")
            
            son_mod, son_hss_durum = yeni_mod, list(hssler)

        if yeni_mod == "intercept" and time.time() - son_guncelleme >= GUNCELLEME_ARALIK:
            son_guncelleme = time.time()
            try:
                h_lat, h_lon = hedef_gps(iha_lat, iha_lon, iha_alt, iha_yaw, cx, cy, boyut)
                ara_yol = arc_rotasi_olustur([(iha_lat, iha_lon), (h_lat, h_lon)], hssler, INTERCEPT_IRTIFA, False)
                g_lat, g_lon, g_alt = ara_yol[-1]
                await misyon_yukle(drone, [wp(g_lat, g_lon, INTERCEPT_IRTIFA, INTERCEPT_HIZ, False, 5)], 0)
                print(f"[INTERCEPT] Yaklaşıyor | Boyut:{boyut*100:.2f}% | ~{boyut_to_mesafe(boyut):.0f}m | yaw:{iha_yaw:.0f}°", end="\r")
            except Exception as e: print(f"[HATA] Hedef takibi: {e}")

# ── Main ────────────────────────────────────────────────────────────
async def main():
    drone = System()
    print("[INTERCEPT] Bağlanılıyor... (udpin://0.0.0.0:14540)")
    await drone.connect(system_address="udpin://0.0.0.0:14540")
    async for state in drone.core.connection_state():
        if state.is_connected: print("[INTERCEPT] ✓ Bağlandı!"); break
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok: print("[INTERCEPT] ✓ GPS hazır!"); break

    await telemetri_al(drone)
    threading.Thread(target=tespit_polling, daemon=True).start()
    threading.Thread(target=telemetri_gonder_thread, daemon=True).start()
    print("[INTERCEPT] Telemetri + Tespit polling başladı")

    await drone.action.arm()
    await drone.action.takeoff()
    async for pos in drone.telemetry.position():
        print(f"[INTERCEPT] Yükseliyor: {pos.relative_altitude_m:.1f}m", end="\r")
        if pos.relative_altitude_m >= 10: print(f"\n[INTERCEPT] ✓ İrtifa: {pos.relative_altitude_m:.1f}m"); break

    await ana_dongu(drone)

if __name__ == "__main__":
    print("=" * 60)
    print("  TEKNOFEST — Intercept + Telemetri (Final - Kalkan Korumalı)")
    print(f"  Yaklaşma:{INTERCEPT_HIZ}m/s | Devriye:{DEVRIYE_HIZ}m/s")
    print("=" * 60)
    try: asyncio.run(main())
    except KeyboardInterrupt: print("\n[INTERCEPT] Durduruldu.")