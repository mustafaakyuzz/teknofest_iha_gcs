"""
algi/yolo_tespit.py — Renk Maskesi + Kalman Filtresi
TrackerCSRT yok — Kalman ile bbox tahmin ve öne kaydırma.
Kalman: IHA'nın hız vektörünü öğrenir, bbox'ı hareket yönünde öne alır.
"""
import os, sys, time, threading, json
import numpy as np, cv2, urllib.request

sys.path.insert(0, os.path.expanduser("~/teknofest_iha"))

MJPEG_URL  = "http://localhost:8554/video"
SUNUCU_URL = "http://localhost:5000"
TESPIT_FPS = 15

AV_MARGIN_X  = 0.25
AV_MARGIN_Y  = 0.10
BB_MIN_BOYUT = 0.06

# Cessna renk aralıkları
KIRMIZI_ALT1 = np.array([0,   100, 80],  np.uint8)
KIRMIZI_UST1 = np.array([10,  255, 255], np.uint8)
KIRMIZI_ALT2 = np.array([165, 100, 80],  np.uint8)
KIRMIZI_UST2 = np.array([180, 255, 255], np.uint8)
BEYAZ_ALT    = np.array([0,   0,  200],  np.uint8)
BEYAZ_UST    = np.array([180, 25, 255],  np.uint8)

GOKYUZU_ORAN = 0.95
MIN_ALAN     = 50
MAX_ALAN     = 8000
MIN_ASPECT   = 1.2
MAX_ASPECT   = 15.0
MIN_DOLULUK  = 0.10
MAX_DOLULUK  = 0.95

# Kalman parametreleri
KALMAN_KAYIP_LIMIT = 30   # frame — bu kadar frame kayıp olursa sıfırla

tespit_lock = threading.Lock()
son_tespit  = {"var": False}
_tespit_sayac = 0
DEBUG = os.getenv("TESPIT_DEBUG", "0") == "1"


# ── Kalman Filtresi ─────────────────────────────────────────────────
class KalmanIzleyici:
    """
    4 durum: [cx, cy, vx, vy]
    2 ölçüm: [cx, cy]
    IHA hızını öğrenir ve bbox'ı öne alır.
    """
    def __init__(self):
        self.kf = cv2.KalmanFilter(4, 2)
        # Durum geçiş matrisi (sabit hız modeli)
        self.kf.transitionMatrix = np.array([
            [1, 0, 1, 0],
            [0, 1, 0, 1],
            [0, 0, 1, 0],
            [0, 0, 0, 1],
        ], np.float32)
        # Ölçüm matrisi
        self.kf.measurementMatrix = np.array([
            [1, 0, 0, 0],
            [0, 1, 0, 0],
        ], np.float32)
        # Gürültü
        self.kf.processNoiseCov     = np.eye(4, dtype=np.float32) * 5e-2
        self.kf.measurementNoiseCov = np.eye(2, dtype=np.float32) * 1e-1
        self.kf.errorCovPost        = np.eye(4, dtype=np.float32)

        self.baslatildi  = False
        self.kayip_sayac = 0
        self.son_bw      = 0
        self.son_bh      = 0

    def baslat(self, cx, cy, bw, bh):
        self.kf.statePost = np.array([[cx], [cy], [0], [0]], np.float32)
        self.baslatildi  = True
        self.kayip_sayac = 0
        self.son_bw      = bw
        self.son_bh      = bh

    def guncelle(self, cx, cy, bw, bh):
        """Ölçüm ile güncelle, düzeltilmiş konumu döndür."""
        if not self.baslatildi:
            self.baslat(cx, cy, bw, bh)
            return cx, cy, 0, 0

        olcum = np.array([[cx], [cy]], np.float32)
        self.kf.correct(olcum)
        self.son_bw      = bw
        self.son_bh      = bh
        self.kayip_sayac = 0

        durum = self.kf.statePost
        return float(durum[0][0]), float(durum[1][0]), float(durum[2][0]), float(durum[3][0])

    def tahmin(self):
        """Ölçüm olmadan tahmin yap (kayıp frame)."""
        if not self.baslatildi:
            return None
        self.kayip_sayac += 1
        if self.kayip_sayac > KALMAN_KAYIP_LIMIT:
            self.baslatildi = False
            return None
        durum = self.kf.predict()
        return float(durum[0][0]), float(durum[1][0]), float(durum[2][0]), float(durum[3][0])

    def one_al(self, cx, cy, vx, vy, dt=0.15):
        """
        Hız vektörüne göre bbox'ı öne kaydır.
        dt: öne alma süresi (saniye) — kamera gecikmesini telafi et
        """
        return cx + vx * dt, cy + vy * dt

    def sifirla(self):
        self.baslatildi = False
        self.kayip_sayac = 0


_kalman = KalmanIzleyici()


# ── MJPEG Okuyucu ───────────────────────────────────────────────────
class MJPEGOkuyucu:
    def __init__(self, url):
        self.url = url; self._s = None; self._buf = b""
        self._lock = threading.Lock(); self._frame = None; self._cal = False

    def _baglan(self):
        try:
            self._s = urllib.request.urlopen(self.url, timeout=5)
            self._buf = b""; print("[MJPEG] Bağlandı"); return True
        except Exception as e:
            print(f"[MJPEG] Hata: {e}"); self._s = None; return False

    def _dongu(self):
        while self._cal:
            if self._s is None:
                if not self._baglan(): time.sleep(2); continue
            try:
                chunk = self._s.read(4096)
                if not chunk: self._s = None; continue
                self._buf += chunk
                while True:
                    a = self._buf.find(b'\xff\xd8'); b = self._buf.find(b'\xff\xd9')
                    if a != -1 and b != -1 and b > a:
                        f = cv2.imdecode(np.frombuffer(self._buf[a:b+2], np.uint8),
                                         cv2.IMREAD_COLOR)
                        self._buf = self._buf[b+2:]
                        if f is not None:
                            with self._lock: self._frame = f
                    else: break
            except Exception as e:
                print(f"[MJPEG] Okuma: {e}"); self._s = None; time.sleep(1)

    def baslat(self):
        self._cal = True
        threading.Thread(target=self._dongu, daemon=True).start()

    def frame_al(self):
        with self._lock:
            return self._frame.copy() if self._frame is not None else None


def sunucuya_gonder(d):
    try:
        req = urllib.request.Request(
            f"{SUNUCU_URL}/api/tespit_durum",
            data=json.dumps(d).encode(),
            headers={"Content-Type": "application/json"},
            method="POST")
        urllib.request.urlopen(req, timeout=0.15)
    except Exception:
        pass


# ── Tespit fonksiyonları ────────────────────────────────────────────
def renk_maskesi(hsv):
    m1 = cv2.inRange(hsv, KIRMIZI_ALT1, KIRMIZI_UST1)
    m2 = cv2.inRange(hsv, KIRMIZI_ALT2, KIRMIZI_UST2)
    mb = cv2.inRange(hsv, BEYAZ_ALT, BEYAZ_UST)
    return cv2.bitwise_or(cv2.bitwise_or(m1, m2), mb)


def morfoloji(maske):
    k1 = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    k2 = cv2.getStructuringElement(cv2.MORPH_RECT,    (5, 3))
    maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN,  k1)
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, k2)
    return maske


def kontur_filtrele(konturlar, h, w):
    adaylar = []
    sinir   = int(h * GOKYUZU_ORAN)
    for k in konturlar:
        alan = cv2.contourArea(k)
        if not (MIN_ALAN <= alan <= MAX_ALAN): continue
        bx, by, bw, bh = cv2.boundingRect(k)
        if by + bh/2 > sinir: continue
        if bh == 0: continue
        aspect = bw / bh
        if not (MIN_ASPECT <= aspect <= MAX_ASPECT): continue
        doluluk = alan / (bw * bh)
        if not (MIN_DOLULUK <= doluluk <= MAX_DOLULUK): continue
        skor = alan * (1.0 - abs(aspect - 3.0) / 6.0)
        adaylar.append((skor, bx, by, bw, bh))
    return sorted(adaylar, reverse=True)


def sartname_kontrol(bx1, by1, bx2, by2, w, h):
    av_x1, av_y1 = w*AV_MARGIN_X,     h*AV_MARGIN_Y
    av_x2, av_y2 = w*(1-AV_MARGIN_X), h*(1-AV_MARGIN_Y)
    cx = (bx1+bx2)/2; cy = (by1+by2)/2
    bw = bx2-bx1;     bh = by2-by1
    av_icinde = (av_x1 <= cx <= av_x2) and (av_y1 <= cy <= av_y2)
    bw_pct    = bw / w; bh_pct = bh / h
    boyut_ok  = (bw_pct >= BB_MIN_BOYUT) or (bh_pct >= BB_MIN_BOYUT)
    return av_icinde, boyut_ok, {
        "boyut_yatay_pct": round(bw_pct*100, 2),
        "boyut_dikey_pct": round(bh_pct*100, 2),
    }


def tespit_et(frame):
    global _tespit_sayac
    h, w = frame.shape[:2]

    hsv   = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    maske = renk_maskesi(hsv)
    maske[int(h*GOKYUZU_ORAN):, :] = 0
    maske = morfoloji(maske)

    konturlar, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    adaylar = kontur_filtrele(konturlar, h, w) if konturlar else []

    if adaylar:
        # Tespit var — Kalman güncelle
        _, bx, by, bw, bh = adaylar[0]
        pad = 6
        bx = max(0, bx-pad); by = max(0, by-pad)
        bw = min(w-bx, bw+2*pad); bh = min(h-by, bh+2*pad)

        raw_cx = bx + bw/2
        raw_cy = by + bh/2

        # Kalman ile düzelt
        kcx, kcy, vx, vy = _kalman.guncelle(raw_cx, raw_cy, bw, bh)

        # Bbox'ı hareket yönünde öne kaydır (50ms)
        one_cx, one_cy = _kalman.one_al(kcx, kcy, vx, vy, dt=0.35)

        # Öne alınmış bbox sınırlarını hesapla
        nbx1 = max(0, int(one_cx - bw/2))
        nby1 = max(0, int(one_cy - bh/2))
        nbx2 = min(w, int(one_cx + bw/2))
        nby2 = min(h, int(one_cy + bh/2))

        _tespit_sayac += 1
        return {
            "bx1": nbx1, "by1": nby1, "bx2": nbx2, "by2": nby2,
            "cx": one_cx, "cy": one_cy,
            "bw": bw, "bh": bh,
            "vx": vx, "vy": vy,
            "kaynak": "renk_maske",
            "aday_sayisi": len(adaylar)
        }
    else:
        # Tespit yok — Kalman tahmini
        tahmin = _kalman.tahmin()
        if tahmin is not None:
            tcx, tcy, vx, vy = tahmin
            bw = _kalman.son_bw; bh = _kalman.son_bh
            if bw > 0 and bh > 0:
                return {
                    "bx1": max(0, int(tcx-bw/2)),
                    "by1": max(0, int(tcy-bh/2)),
                    "bx2": min(w, int(tcx+bw/2)),
                    "by2": min(h, int(tcy+bh/2)),
                    "cx": tcx, "cy": tcy,
                    "bw": bw,  "bh": bh,
                    "vx": vx,  "vy": vy,
                    "kaynak": "kalman_tahmin",
                    "aday_sayisi": 0
                }
        return None


def isle(frame):
    h, w = frame.shape[:2]
    t    = tespit_et(frame)

    if t is None:
        d = {"var": False, "zaman": time.time()}
        with tespit_lock: son_tespit.update(d)
        sunucuya_gonder(d)
        return

    bx1,by1,bx2,by2 = int(t["bx1"]),int(t["by1"]),int(t["bx2"]),int(t["by2"])
    av_icinde, boyut_ok, boyut = sartname_kontrol(bx1,by1,bx2,by2,w,h)
    kilit = av_icinde and boyut_ok

    # Kalman tahminiyse güveni düşür — kilitlenme_hazir False yap
    kalman_tahmin = t.get("kaynak") == "kalman_tahmin"
    if False:  # kalman_tahmin kontrolü kaldırıldı
        kilit = False   # Sadece gerçek tespitten kilitlenme

    d = {
        "var":              True,
        "conf":             0.85 if kalman_tahmin else 0.92,
        "sinif":            "hedef_iha",
        "bx1": bx1, "by1": by1, "bx2": bx2, "by2": by2,
        "cx":  t["cx"]/w, "cy": t["cy"]/h,
        "w":   t["bw"]/w, "h":  t["bh"]/h,
        "av_icinde":        av_icinde,
        "boyut_ok":         boyut_ok,
        "boyut_yatay_pct":  boyut["boyut_yatay_pct"],
        "boyut_dikey_pct":  boyut["boyut_dikey_pct"],
        "kilitlenme_hazir": kilit,
        "takip_aktif":      not kalman_tahmin,
        "track_id":         0 if not kalman_tahmin else -1,
        "kaynak":           t.get("kaynak","?"),
        "zaman":            time.time(),
    }
    with tespit_lock: son_tespit.update(d)
    sunucuya_gonder(d)

    if kilit:
        print(f"[TESPİT] ✓ KİLİT HAZIR | "
              f"Y:{boyut['boyut_yatay_pct']:.1f}% "
              f"D:{boyut['boyut_dikey_pct']:.1f}% | "
              f"AV:✓ | src:{t.get('kaynak','?')}")
    elif av_icinde:
        print(f"[TESPİT] ~ Tespit | "
              f"Y:{boyut['boyut_yatay_pct']:.1f}% "
              f"D:{boyut['boyut_dikey_pct']:.1f}% | "
              f"AV:✓ Boyut:{'✓' if boyut_ok else '✗'} | "
              f"src:{t.get('kaynak','?')}", end="\r")

    if DEBUG:
        vis = frame.copy()
        renk = (0,255,0) if kilit else ((0,165,255) if av_icinde else (0,0,255))
        cv2.rectangle(vis, (bx1,by1), (bx2,by2), renk, 2)
        av_x1,av_y1 = int(w*AV_MARGIN_X),int(h*AV_MARGIN_Y)
        av_x2,av_y2 = int(w*(1-AV_MARGIN_X)),int(h*(1-AV_MARGIN_Y))
        cv2.rectangle(vis, (av_x1,av_y1), (av_x2,av_y2), (0,255,255), 1)
        vx = t.get("vx",0); vy = t.get("vy",0)
        cx_i = int(t["cx"]); cy_i = int(t["cy"])
        cv2.arrowedLine(vis, (cx_i,cy_i),
                        (cx_i+int(vx*3), cy_i+int(vy*3)), (255,0,0), 2)
        cv2.imshow("Tespit Debug", vis)
        cv2.waitKey(1)


def dongu(okuyucu):
    aralik = 1.0/TESPIT_FPS; bos = 0
    print(f"[TESPİT] Renk Maskesi + Kalman | FPS:{TESPIT_FPS}")
    print(f"         AV:%{AV_MARGIN_X*100:.0f}x | Min:%{BB_MIN_BOYUT*100:.0f} | Debug:TESPIT_DEBUG=1")
    while True:
        t0    = time.monotonic()
        frame = okuyucu.frame_al()
        if frame is None:
            bos += 1
            if bos % 50 == 0: print("[TESPİT] Frame yok...")
            time.sleep(0.1); continue
        bos = 0
        try: isle(frame)
        except Exception as e:
            print(f"[TESPİT] Hata: {e}")
            import traceback; traceback.print_exc()
        gecen = time.monotonic() - t0
        if aralik - gecen > 0: time.sleep(aralik - gecen)


if __name__ == "__main__":
    print("="*60)
    print("  TEKNOFEST — Renk Maskesi + Kalman Filtresi")
    print(f"  Tracker yok — Kalman bbox'ı öne alır")
    print("="*60)
    okuyucu = MJPEGOkuyucu(MJPEG_URL)
    okuyucu.baslat()
    print("[TESPİT] MJPEG bekleniyor (3s)...")
    time.sleep(3)
    threading.Thread(target=dongu, args=(okuyucu,), daemon=True).start()
    try:
        while True:
            time.sleep(5)
            with tespit_lock: d = son_tespit.copy()
            if d.get("var"):
                print(f"\n[TESPİT] ✓ Y:{d.get('boyut_yatay_pct',0):.1f}% "
                      f"D:{d.get('boyut_dikey_pct',0):.1f}% "
                      f"Kilit:{d.get('kilitlenme_hazir')} "
                      f"src:{d.get('kaynak','?')}")
            else:
                print(f"\n[TESPİT] Hedef yok | Sayı:{_tespit_sayac}")
    except KeyboardInterrupt:
        print("\n[TESPİT] Durduruldu.")