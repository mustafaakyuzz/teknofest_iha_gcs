"""
sim/hedef_iha.py — FINAL
Hedef IHA, ana uçağın devriye rotasının TAM ÜZERİNDE uçar.
Elips yarıçapı = devriye alanı yarıçapı → her waypoint'te karşılaşırlar.
"""
import os, time, math, threading, subprocess
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

try:
    from gz.transport13 import Node
    from gz.msgs10.pose_pb2 import Pose
    from gz.msgs10.boolean_pb2 import Boolean
    GZ_AVAILABLE = True
    print("[HEDEF] gz.transport13 OK")
except ImportError:
    GZ_AVAILABLE = False
    print("[HEDEF] gz.transport yok — subprocess fallback")

# ─── AYARLAR ───────────────────────────────────────────────────────
MODEL_ADI = "hedef_iha"
SDF_DOSYA = os.path.expanduser("~/teknofest_iha/sim/hedef_cessna.sdf")

# Devriye alanının tam merkezi ve boyutları
# Gazebo: X[-156, 55] Y[-52, 81] → merkez(-50, 14) boyut 211x134m
MERKEZ_X  = -50.0
MERKEZ_Y  =  14.4
MERKEZ_Z  =  60.0   # Ana uçakla AYNI irtifa

# Elips = devriye rotasının üzerinde
# Biraz küçültelim ki tam rotanın içinde kalsın (kenarları %85)
YARI_CAPX =  15.0   # 211/2 * 0.9
YARI_CAPY =  12.0   # 134/2 * 0.9

# İrtifa dalgalanması kapalı — sabit 60m, kamera kaçırmasın
IRTIFA_DALGA_GENLIK  = 0.0

# Hız — ana uçak 10m/s, hedef biraz yavaş → daha uzun süre kamerada kalır
HIZ_MS        = 6.0
GUNCELLEME_HZ = 30

CEVRE       = math.pi * (YARI_CAPX + YARI_CAPY)
PERIYOT_S   = CEVRE / HIZ_MS
ACIKSAL_HIZ = (2.0 * math.pi) / PERIYOT_S  # CW için - işaret kullanılacak

# Başlangıç: WP0'a en yakın nokta (elipsin sağ ucu = x maksimum)
# WP0 = (-50+95, 14) = (45, 14) → WP0 Gazebo = (-50, 81)
# WP0'a yakın başlamak için açıyı hesapla
# aci=0 → (merkez_x+rx, merkez_y) = (45, 14.4) — WP1'e yakın
# aci=π/2 → (merkez_x, merkez_y+ry) = (-50, 74.4) — WP0'a çok yakın!
BASLANGIC_ACI = math.pi / 2   # WP0 (~-50, 81) yakınından başla


# ─── SPAWN ─────────────────────────────────────────────────────────
def spawn_model():
    bx = MERKEZ_X + YARI_CAPX * math.cos(BASLANGIC_ACI)
    by = MERKEZ_Y + YARI_CAPY * math.sin(BASLANGIC_ACI)

    subprocess.run([
        "gz", "service", "-s", "/world/default/remove",
        "--reqtype", "gz.msgs.Entity", "--reptype", "gz.msgs.Boolean",
        "--timeout", "2000", "--req", f'name: "{MODEL_ADI}" type: 2'
    ], capture_output=True, timeout=5)
    time.sleep(0.8)

    r = subprocess.run([
        "gz", "service", "-s", "/world/default/create",
        "--reqtype", "gz.msgs.EntityFactory", "--reptype", "gz.msgs.Boolean",
        "--timeout", "8000", "--req",
        f'sdf_filename: "{SDF_DOSYA}" name: "{MODEL_ADI}" '
        f'pose: {{position: {{x: {bx:.1f}, y: {by:.1f}, z: {MERKEZ_Z:.1f}}}}}'
    ], capture_output=True, text=True, timeout=15)

    ok = "true" in r.stdout or r.returncode == 0
    print(f"[HEDEF] Spawn {'OK ✓' if ok else 'HATA: '+r.stderr.strip()}")
    print(f"[HEDEF] Başlangıç: ({bx:.0f}, {by:.0f}, {MERKEZ_Z:.0f}m)")
    print(f"[HEDEF] WP0 konumu: (-50, 81) — mesafe: {math.hypot(bx-(-50), by-81):.0f}m")
    print(f"[HEDEF] Elips: {YARI_CAPX:.0f}x{YARI_CAPY:.0f}m | "
          f"periyot:{PERIYOT_S:.0f}s | hız:{HIZ_MS}m/s")
    return ok


# ─── POSE PUBLISHER ────────────────────────────────────────────────
class NativePosePub:
    def __init__(self):
        self._node = Node()
        self._hata = 0

    def gonder(self, x, y, z, yaw):
        cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
        try:
            pose = Pose()
            pose.name = MODEL_ADI
            pose.position.x = x
            pose.position.y = y
            pose.position.z = z
            pose.orientation.x = 0.0
            pose.orientation.y = 0.0
            pose.orientation.z = sy
            pose.orientation.w = cy
            rep = Boolean()
            result, rep = self._node.request(
                "/world/default/set_pose", pose, Pose, Boolean, 500
            )
            if result and rep.data:
                self._hata = 0
                return True
        except Exception as e:
            self._hata += 1
            if self._hata % 60 == 1:
                print(f"[HEDEF] Native hata #{self._hata}: {e}")
        return False


class SubprocessPosePub:
    def __init__(self):
        self._hata = 0

    def gonder(self, x, y, z, yaw):
        cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
        req = (f'name: "{MODEL_ADI}" '
               f'position: {{x: {x:.3f}, y: {y:.3f}, z: {z:.3f}}} '
               f'orientation: {{x: 0.0, y: 0.0, z: {sy:.5f}, w: {cy:.5f}}}')
        try:
            r = subprocess.run(
                ["gz", "service", "-s", "/world/default/set_pose",
                 "--reqtype", "gz.msgs.Pose", "--reptype", "gz.msgs.Boolean",
                 "--timeout", "300", "--req", req],
                capture_output=True, text=True, timeout=0.6
            )
            return "true" in r.stdout
        except Exception:
            self._hata += 1
            return False


# ─── ANA SINIF ─────────────────────────────────────────────────────
class HedefIHA:
    def __init__(self):
        self.aci = BASLANGIC_ACI
        self.x   = MERKEZ_X + YARI_CAPX * math.cos(self.aci)
        self.y   = MERKEZ_Y + YARI_CAPY * math.sin(self.aci)
        self.z   = MERKEZ_Z
        self.yaw = 0.0
        self._cal = False
        self._tur = 0

        if GZ_AVAILABLE:
            try:
                self._pub = NativePosePub()
                print("[HEDEF] Native IPC publisher aktif")
            except Exception as e:
                print(f"[HEDEF] Native hata ({e}), subprocess kullanılıyor")
                self._pub = SubprocessPosePub()
        else:
            self._pub = SubprocessPosePub()

    @property
    def konum(self):
        return {"x": self.x, "y": self.y, "z": self.z, "yaw": self.yaw}

    def _dongu(self):
        dt = 1.0 / GUNCELLEME_HZ
        while self._cal:
            t0 = time.monotonic()

            # CW dönüş (devriye ile aynı yön)
            self.aci -= ACIKSAL_HIZ * dt

            if self.aci <= -2 * math.pi * (self._tur + 1):
                self._tur += 1
                print(f"[HEDEF] Tur {self._tur} tamamlandı")

            self.x = MERKEZ_X + YARI_CAPX * math.cos(self.aci)
            self.y = MERKEZ_Y + YARI_CAPY * math.sin(self.aci)
            self.z = MERKEZ_Z  # Sabit irtifa — kamera kaçırmasın

            # Teğet yönüne bak (CW)
            tx =  YARI_CAPX * math.sin(self.aci)
            ty = -YARI_CAPY * math.cos(self.aci)
            self.yaw = math.atan2(ty, tx)

            self._pub.gonder(self.x, self.y, self.z, self.yaw)

            gecen = time.monotonic() - t0
            if gecen < dt:
                time.sleep(dt - gecen)

    def baslat(self):
        self._cal = True
        threading.Thread(target=self._dongu, daemon=True, name="HedefYorunge").start()
        print(f"[HEDEF] Başladı | CW | {GUNCELLEME_HZ}Hz | {HIZ_MS}m/s | "
              f"periyot:{PERIYOT_S:.0f}s")

    def durdur(self):
        self._cal = False

    def durum(self):
        aci_d = math.degrees(self.aci % (2 * math.pi))
        print(f"[HEDEF] açı:{aci_d:5.1f}° "
              f"pos:({self.x:6.1f},{self.y:6.1f},{self.z:5.1f}) "
              f"tur:{self._tur} err:{self._pub._hata}")


# ─── MAIN ──────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 60)
    print("  TEKNOFEST 2026 — Hedef IHA FINAL")
    print(f"  Devriye rotası üzerinde | {YARI_CAPX:.0f}x{YARI_CAPY:.0f}m elips")
    print(f"  İrtifa: {MERKEZ_Z}m sabit | Hız: {HIZ_MS}m/s | CW")
    print("=" * 60)

    spawn_model()
    print("[HEDEF] 3s bekleniyor...")
    time.sleep(3.0)

    hedef = HedefIHA()
    hedef.baslat()

    try:
        while True:
            time.sleep(4.0)
            hedef.durum()
    except KeyboardInterrupt:
        print("\n[HEDEF] Durduruluyor...")
        hedef.durdur()
        print("[HEDEF] Çıkış.")