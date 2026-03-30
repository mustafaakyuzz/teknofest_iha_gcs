"""
algi/yolo_tespit.py — MOG2 + akıllı filtre
Sadece gökyüzü bölgesindeki, doğru boyuttaki, aspect ratio'su uçağa benzeyen nesneleri al.
"""
import os, sys, time, threading, json
import numpy as np, cv2, urllib.request

sys.path.insert(0, os.path.expanduser("~/teknofest_iha"))

MJPEG_URL  = "http://localhost:8554/video"
SUNUCU_URL = "http://localhost:5000"
TESPIT_FPS = 15

AV_MARGIN_X  = 0.25
AV_MARGIN_Y  = 0.10
BB_MIN_BOYUT = 0.05

# ── Filtre parametreleri ────────────────────────────────────────────
# Gökyüzü bölgesi: görüntünün üst %60'ı (zemin/yer hariç)
GOKYUZU_ORAN     = 0.65

# Kontur boyut filtresi (piksel²)
MIN_ALAN         = 8     # çok küçük gürültü ele
MAX_ALAN         = 3000  # çok büyük (zemin, bulut vs) ele

# Aspect ratio filtresi — cessna modeli yatay uzun
# genişlik/yükseklik oranı: uçak 2:1 ile 8:1 arası
MIN_ASPECT       = 1.5
MAX_ASPECT       = 12.0

# Doluluk oranı — kontur alanı / bbox alanı
# Uçak şekli: 0.2 - 0.7 arası (çok küçük veya tam dolu değil)
MIN_DOLULUK      = 0.15
MAX_DOLULUK      = 0.85

# MOG2 ayarları
MOG2_HISTORY    = 50
MOG2_THRESHOLD  = 25
ISITMA_FRAME    = 30

_bg  = cv2.createBackgroundSubtractorMOG2(
    history=MOG2_HISTORY, varThreshold=MOG2_THRESHOLD, detectShadows=False)
_k3  = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
_k2  = cv2.getStructuringElement(cv2.MORPH_RECT,    (2, 2))

tespit_lock  = threading.Lock()
son_tespit   = {"var": False}
_frame_sayac = 0


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
                        f = cv2.imdecode(np.frombuffer(self._buf[a:b+2], np.uint8), cv2.IMREAD_COLOR)
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
        urllib.request.urlopen(req, timeout=0.1)
    except Exception:
        pass


def ucak_mi(kontur, bx, by, bw, bh, img_h):
    """Konturun uçak olup olmadığını filtrele."""
    # 1) Gökyüzü bölgesinde mi?
    cy = by + bh / 2
    if cy > img_h * GOKYUZU_ORAN:
        return False, "zemin"

    # 2) Boyut
    alan = cv2.contourArea(kontur)
    if not (MIN_ALAN <= alan <= MAX_ALAN):
        return False, f"boyut:{alan:.0f}"

    # 3) Aspect ratio — uçak yatay uzun
    if bh == 0:
        return False, "bh=0"
    aspect = bw / bh
    if not (MIN_ASPECT <= aspect <= MAX_ASPECT):
        return False, f"aspect:{aspect:.1f}"

    # 4) Doluluk oranı
    bbox_alan = bw * bh
    if bbox_alan == 0:
        return False, "bbox=0"
    doluluk = alan / bbox_alan
    if not (MIN_DOLULUK <= doluluk <= MAX_DOLULUK):
        return False, f"doluluk:{doluluk:.2f}"

    return True, "OK"


def tespit_et(frame):
    global _frame_sayac
    h, w = frame.shape[:2]

    # MOG2 uygula
    maske = _bg.apply(frame)
    _frame_sayac += 1

    if _frame_sayac < ISITMA_FRAME:
        return None

    # Morfoloji — küçük gürültü temizle, parçaları birleştir
    maske = cv2.morphologyEx(maske, cv2.MORPH_OPEN,  _k2)
    maske = cv2.morphologyEx(maske, cv2.MORPH_CLOSE, _k3)

    # Sadece gökyüzü bölgesini işle
    gokyuzu_siniri = int(h * GOKYUZU_ORAN)
    maske[gokyuzu_siniri:, :] = 0

    konturlar, _ = cv2.findContours(maske, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not konturlar:
        return None

    # Her kontura filtre uygula
    adaylar = []
    for k in konturlar:
        bx, by, bw, bh = cv2.boundingRect(k)
        gecerli, sebep = ucak_mi(k, bx, by, bw, bh, h)
        if gecerli:
            adaylar.append((cv2.contourArea(k), bx, by, bw, bh))

    if not adaylar:
        return None

    # En büyük adayı al
    adaylar.sort(reverse=True)
    _, bx, by, bw, bh = adaylar[0]

    pad = 4
    bx  = max(0, bx - pad)
    by  = max(0, by - pad)
    bw  = min(w - bx, bw + 2*pad)
    bh  = min(h - by, bh + 2*pad)

    return {
        "bx1": bx, "by1": by, "bx2": bx+bw, "by2": by+bh,
        "cx": bx+bw/2, "cy": by+bh/2,
        "bw": bw, "bh": bh,
        "aday_sayisi": len(adaylar)
    }


def sartname_kontrol(bx1, by1, bx2, by2, w, h):
    av_x1, av_y1 = w*AV_MARGIN_X, h*AV_MARGIN_Y
    av_x2, av_y2 = w*(1-AV_MARGIN_X), h*(1-AV_MARGIN_Y)
    cx = (bx1+bx2)/2; cy = (by1+by2)/2
    bw = bx2-bx1;     bh = by2-by1
    av_icinde = (av_x1 <= cx <= av_x2) and (av_y1 <= cy <= av_y2)
    by_  = bw/w; bd_  = bh/h
    boyut_ok = (by_ >= BB_MIN_BOYUT) or (bd_ >= BB_MIN_BOYUT)
    return av_icinde, boyut_ok, {"boyut_yatay_pct": round(by_*100,1),
                                  "boyut_dikey_pct": round(bd_*100,1)}


def isle(frame):
    h, w = frame.shape[:2]
    t = tespit_et(frame)

    if t is None:
        d = {"var": False, "zaman": time.time()}
        with tespit_lock: son_tespit.update(d)
        sunucuya_gonder(d)
        return

    bx1,by1,bx2,by2 = int(t["bx1"]),int(t["by1"]),int(t["bx2"]),int(t["by2"])
    av_icinde, boyut_ok, boyut = sartname_kontrol(bx1,by1,bx2,by2,w,h)
    kilit = av_icinde and boyut_ok

    d = {
        "var": True, "conf": 0.88, "sinif": "hedef_iha",
        "bx1":bx1,"by1":by1,"bx2":bx2,"by2":by2,
        "cx": t["cx"]/w, "cy": t["cy"]/h,
        "w":  t["bw"]/w, "h":  t["bh"]/h,
        "av_icinde": av_icinde, "boyut_ok": boyut_ok,
        "boyut_yatay_pct": boyut["boyut_yatay_pct"],
        "boyut_dikey_pct": boyut["boyut_dikey_pct"],
        "kilitlenme_hazir": kilit,
        "takip_aktif": False, "track_id": -1,
        "zaman": time.time(), "aday_sayisi": t["aday_sayisi"],
    }
    with tespit_lock: son_tespit.update(d)
    sunucuya_gonder(d)

    print(f"[TESPIT] ✓ Y{boyut['boyut_yatay_pct']:.1f}% D{boyut['boyut_dikey_pct']:.1f}% "
          f"| AV:{'✓' if av_icinde else '✗'} "
          f"| Kilit:{'✓' if kilit else '✗'} "
          f"| Adaylar:{t['aday_sayisi']}")


def dongu(okuyucu):
    aralik = 1.0/TESPIT_FPS; bos = 0
    print(f"[TESPIT] MOG2 + Filtre | Isınma:{ISITMA_FRAME}f | "
          f"Aspect:{MIN_ASPECT}-{MAX_ASPECT}")
    while True:
        frame = okuyucu.frame_al()
        if frame is None:
            bos += 1
            if bos % 30 == 0: print("[TESPIT] Frame yok")
            time.sleep(0.1); continue
        bos = 0
        try: isle(frame)
        except Exception as e: print(f"[TESPIT] Hata: {e}")
        time.sleep(aralik)


if __name__ == "__main__":
    print("="*55)
    print("TEKNOFEST — MOG2 + Akıllı Filtre (gökyüzü+aspect+doluluk)")
    print(f"Gökyüzü: üst %{GOKYUZU_ORAN*100:.0f} | "
          f"Aspect: {MIN_ASPECT}-{MAX_ASPECT}")
    print("="*55)
    okuyucu = MJPEGOkuyucu(MJPEG_URL)
    okuyucu.baslat()
    time.sleep(2)
    threading.Thread(target=dongu, args=(okuyucu,), daemon=True).start()
    try:
        while True:
            time.sleep(5)
            with tespit_lock: d = son_tespit.copy()
            if d.get("var"):
                print(f"[TESPIT] ✓ Y{d.get('boyut_yatay_pct',0):.1f}% "
                      f"D{d.get('boyut_dikey_pct',0):.1f}% "
                      f"Kilit:{d['kilitlenme_hazir']}")
            else: print("[TESPIT] Hedef yok")
    except KeyboardInterrupt: print("\n[TESPIT] Durduruldu.")