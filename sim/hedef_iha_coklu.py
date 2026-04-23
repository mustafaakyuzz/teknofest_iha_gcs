"""
sim/hedef_iha_coklu.py — Gerçekçi hareket
- Doğrusal uçuş + rastgele yön değiştirme
- Saha sınırı: PX4 origin etrafında ±150m
- Native IPC (GZ_IP=127.0.0.1)
- python3 ile çalıştır
"""
import os, time, math, random, threading, subprocess
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"
os.environ["GZ_IP"] = "127.0.0.1"

try:
    from gz.transport13 import Node
    from gz.msgs10.pose_pb2 import Pose
    from gz.msgs10.boolean_pb2 import Boolean
    NATIVE_IPC = True
except ImportError:
    print("[HEDEF] gz.transport13 bulunamadı")
    NATIVE_IPC = False

SDF_DOSYA = os.path.expanduser("~/teknofest_iha/sim/hedef_cessna.sdf")

# ── Saha sınırları (Gazebo metre) ───────────────────────────────────
SAHA_X_MIN = -150.0
SAHA_X_MAX =  150.0
SAHA_Y_MIN = -150.0
SAHA_Y_MAX =  150.0
IRTIFA     =  70.0

# ── IHA konfigürasyonu ──────────────────────────────────────────────
# (isim, baslangic_x, baslangic_y, hiz_m_s)
IHALAR = [
    ("hedef_iha_1",   0.0,   0.0,  12.0),
    ("hedef_iha_2",  50.0,  70.0,  12.0),
    ("hedef_iha_3", -50.0, -100.0,  12.0),
]

GUNCELLEME_HZ     = 20
YON_DEGISTIRME_SN = 8.0   # Her 8 saniyede bir yön değiştir


def spawn_iha(model_adi, bx, by, bz):
    subprocess.run([
        "gz", "service", "-s", "/world/default/remove",
        "--reqtype", "gz.msgs.Entity", "--reptype", "gz.msgs.Boolean",
        "--timeout", "2000", "--req", f'name: "{model_adi}" type: 2'
    ], capture_output=True, timeout=5, env={**os.environ})
    time.sleep(0.8)

    r = subprocess.run([
        "gz", "service", "-s", "/world/default/create",
        "--reqtype", "gz.msgs.EntityFactory", "--reptype", "gz.msgs.Boolean",
        "--timeout", "10000", "--req",
        f'sdf_filename: "{SDF_DOSYA}" name: "{model_adi}" '
        f'pose: {{position: {{x: {bx:.2f}, y: {by:.2f}, z: {bz:.2f}}}}}'
    ], capture_output=True, text=True, timeout=15, env={**os.environ})

    ok = "true" in r.stdout.lower() or r.returncode == 0
    print(f"  {'✓' if ok else '✗'} {model_adi} @ ({bx:.1f},{by:.1f},{bz:.1f}m)")
    return ok


def iha_dongu(node, model_adi, baslangic_x, baslangic_y, hiz):
    """
    Gerçekçi doğrusal uçuş:
    - Rastgele yön seç, düz uç
    - Saha sınırına yaklaşınca veya belirli sürede yön değiştir
    - Yön değişiminde yumuşak dönüş (açısal hız sınırlı)
    """
    dt   = 1.0 / GUNCELLEME_HZ
    x, y = baslangic_x, baslangic_y
    yaw  = random.uniform(0, 2 * math.pi)   # Başlangıç yönü
    hedef_yaw = yaw
    son_yon_degisim = time.time()
    hatalar = 0
    son_hata_log = 0

    # Maksimum açısal dönüş hızı (rad/s) — gerçekçi sabit kanat
    MAX_YAW_HIZI = math.radians(30)   # 30°/s

    def yeni_yon_sec(x, y):
        """Saha sınırından uzaklaştıracak yön seç."""
        # Merkeze doğru bileşen + rastgelelik
        merkez_aci = math.atan2(-y, -x)
        rastgele   = random.uniform(-math.pi/2, math.pi/2)
        return merkez_aci + rastgele

    while True:
        t0 = time.monotonic()

        # ── Yön değiştirme kararı ────────────────────────────────
        simdi = time.time()
        sinira_yakin = (x < SAHA_X_MIN + 20 or x > SAHA_X_MAX - 20 or
                        y < SAHA_Y_MIN + 20 or y > SAHA_Y_MAX - 20)

        if sinira_yakin or simdi - son_yon_degisim > YON_DEGISTIRME_SN:
            hedef_yaw = yeni_yon_sec(x, y)
            son_yon_degisim = simdi

        # ── Yumuşak yön geçişi ───────────────────────────────────
        fark = (hedef_yaw - yaw + math.pi) % (2 * math.pi) - math.pi
        max_donus = MAX_YAW_HIZI * dt
        if abs(fark) < max_donus:
            yaw = hedef_yaw
        else:
            yaw += math.copysign(max_donus, fark)
        yaw = yaw % (2 * math.pi)

        # ── Pozisyon güncelle ────────────────────────────────────
        x += hiz * math.cos(yaw) * dt
        y += hiz * math.sin(yaw) * dt

        # Saha sınırı klamp
        x = max(SAHA_X_MIN, min(SAHA_X_MAX, x))
        y = max(SAHA_Y_MIN, min(SAHA_Y_MAX, y))

        # ── Quaternion (yaw) ─────────────────────────────────────
        qz = math.sin(yaw * 0.5)
        qw = math.cos(yaw * 0.5)

        # ── Pose gönder ──────────────────────────────────────────
        pose = Pose()
        pose.name          = model_adi
        pose.position.x    = x
        pose.position.y    = y
        pose.position.z    = IRTIFA
        pose.orientation.x = 0.0
        pose.orientation.y = 0.0
        pose.orientation.z = qz
        pose.orientation.w = qw

        try:
            result, rep = node.request(
                "/world/default/set_pose", pose, Pose, Boolean, 200)
            if not (result and rep.data):
                hatalar += 1
        except Exception as e:
            hatalar += 1
            if time.time() - son_hata_log > 10:
                print(f"[{model_adi}] IPC hata: {e}")
                son_hata_log = time.time()

        gecen = time.monotonic() - t0
        kalan = dt - gecen
        if kalan > 0:
            time.sleep(kalan)


if __name__ == "__main__":
    print("=" * 56)
    print(f"  TEKNOFEST 2026 — {len(IHALAR)} Hedef IHA (Gerçekçi)")
    print(f"  Saha: ±150m | İrtifa:{IRTIFA}m | Yön:{YON_DEGISTIRME_SN}s")
    print("=" * 56)

    print("\n[HEDEF] Spawn ediliyor...")
    for cfg in IHALAR:
        model_adi, bx, by, hiz = cfg
        spawn_iha(model_adi, bx, by, IRTIFA)
        time.sleep(1.2)

    print(f"\n[HEDEF] Gazebo yerleşimi bekleniyor (3s)...")
    time.sleep(3.0)

    if not NATIVE_IPC:
        print("[HEDEF] HATA: Native IPC yok, GZ_IP export edilmemiş!")
        exit(1)

    node = Node()
    print(f"[HEDEF] Native IPC hazır\n")

    for cfg in IHALAR:
        model_adi, bx, by, hiz = cfg
        threading.Thread(
            target=iha_dongu,
            args=(node, model_adi, bx, by, hiz),
            daemon=True,
            name=f"T-{model_adi}"
        ).start()
        print(f"  ✓ {model_adi} | {hiz}m/s | baslangic:({bx:.0f},{by:.0f})")

    print(f"\n[HEDEF] {len(IHALAR)} IHA aktif!\n")
    try:
        while True:
            time.sleep(10)
            print(f"[HEDEF] {len(IHALAR)} IHA çalışıyor | {GUNCELLEME_HZ}Hz")
    except KeyboardInterrupt:
        print("\n[HEDEF] Durduruldu.")