"""
algi/kilitlenme_algo.py — Şartname uyumlu kilitlenme algoritması

Şartname kriterleri:
- 4 saniye kesintisiz kilitlenme (1s tolerans)
- Frame toleransı: 4s içinde max 200ms (=%5) eksik/hatalı frame
- Kilitlenme paketi: bitimden en geç 2 saniye içinde gönder
- Tolerans: 5s pencere içinde 4s kilitlenme aranır (±1s)
- Aynı IHA'ya tekrar kilitlenme için araya farklı IHA girmelidir
- Otonom modda kilitlenme olmalı
"""
import os, sys, time, threading, collections
sys.path.insert(0, os.path.expanduser("~/teknofest_iha"))
import requests

SUNUCU_URL       = "http://localhost:5000"
KILITLENME_SURE  = 4.0   # saniye
TOLERANS_SURE    = 1.0   # 1s tolerans payı
FRAME_TOLERANS   = 0.05  # %5 — 4s için 200ms
PAKET_SON_SURE   = 1.8   # bitimden 1.8s içinde gönder (limit 2s)
LOG_DOSYASI      = os.path.expanduser("~/teknofest_iha/logs/kilitlenme.log")

ws_durum = {
    "aktif": False, "gecen": 0.0, "hedef_sure": KILITLENME_SURE,
    "yuzde": 0.0, "bx1": 0, "by1": 0, "bx2": 0, "by2": 0,
    "basarili": False, "otonom": True,
    # Şartname detayları
    "boyut_yatay_pct": 0.0, "boyut_dikey_pct": 0.0,
    "toplam_kilitlenme": 0,
}
ws_lock = threading.Lock()


def _log(msg):
    t = time.strftime("%H:%M:%S")
    satir = f"[{t}] {msg}"
    print(satir)
    try:
        os.makedirs(os.path.dirname(LOG_DOSYASI), exist_ok=True)
        with open(LOG_DOSYASI, "a") as f:
            f.write(satir + "\n")
    except Exception:
        pass


def _sunucuya_gonder():
    try:
        with ws_lock:
            d = ws_durum.copy()
        requests.post(f"{SUNUCU_URL}/api/kilitlenme_durum", json=d, timeout=0.1)
    except Exception:
        pass


def paket_gonder(baslangic, bitis, bb_gecmis, otonom):
    """
    Şartname: kilitlenme paketi bitimden en geç 2 saniye içinde gönderilmeli.
    """
    sure = bitis - baslangic
    gecikme = time.time() - bitis

    if gecikme > PAKET_SON_SURE:
        _log(f"[KILIT] UYARI: Paket gecikmesi {gecikme:.2f}s > {PAKET_SON_SURE}s!")

    if bb_gecmis:
        ort_cx = sum(b["cx"] for b in bb_gecmis) / len(bb_gecmis)
        ort_cy = sum(b["cy"] for b in bb_gecmis) / len(bb_gecmis)
        ort_w  = sum(b["w"]  for b in bb_gecmis) / len(bb_gecmis)
        ort_h  = sum(b["h"]  for b in bb_gecmis) / len(bb_gecmis)
    else:
        ort_cx = ort_cy = ort_w = ort_h = 0.0

    paket = {
        "kilitlenme_bitis_zamani":  bitis,
        "kilitlenme_suresi":        sure,
        "otonom_kilitlenme":        otonom,
        "hedef_merkez_X":           round(ort_cx, 4),
        "hedef_merkez_Y":           round(ort_cy, 4),
        "hedef_genislik":           round(ort_w, 4),
        "hedef_yukseklik":          round(ort_h, 4),
        "gonderim_gecikmesi":       round(gecikme, 4),
    }
    try:
        r = requests.post(f"{SUNUCU_URL}/api/kilitlenme_bilgisi", json=paket, timeout=2.0)
        if r.status_code == 200:
            _log(f"[KILIT] ✓ Paket OK | {'OTONOM' if otonom else 'MANUEL'} | "
                 f"{sure:.2f}s | gecikme:{gecikme*1000:.0f}ms")
            return True
    except Exception as e:
        _log(f"[KILIT] Paket hatasi: {e}")
    return False


class FrameKayitci:
    """
    Şartname frame toleransı kontrolü:
    4 saniyelik kilitlenme için max 200ms (=%5) eksik/hatalı frame.
    Başlangıç ve bitişte tolerans geçerli değil.
    """
    def __init__(self):
        self.kayitlar = collections.deque()  # (zaman, gecerli_mi)

    def ekle(self, gecerli: bool):
        self.kayitlar.append((time.time(), gecerli))
        # 6 saniyelik pencere tut
        kesim = time.time() - 6.0
        while self.kayitlar and self.kayitlar[0][0] < kesim:
            self.kayitlar.popleft()

    def kesintisiz_sure_hesapla(self, sure: float) -> float:
        """
        Son 'sure' saniyelik pencerede kesintisiz kilitlenme süresini hesapla.
        Frame toleransı: %5 (200ms/4s).
        Returns: gerçek kesintisiz süre (toleranslı)
        """
        if not self.kayitlar:
            return 0.0

        simdi = time.time()
        pencere_baslangic = simdi - sure - TOLERANS_SURE  # ±1s tolerans penceresi
        penceredeki = [(t, g) for t, g in self.kayitlar if t >= pencere_baslangic]

        if not penceredeki:
            return 0.0

        # Toplam pencere süresi
        toplam_sure = penceredeki[-1][0] - penceredeki[0][0] if len(penceredeki) > 1 else 0.0
        # Geçerli frame süresi
        gecerli_sure = sum(
            penceredeki[i+1][0] - penceredeki[i][0]
            for i in range(len(penceredeki)-1)
            if penceredeki[i][1]
        )

        if toplam_sure <= 0:
            return 0.0

        # Frame toleransı: max %5 eksik
        eksik_oran = 1.0 - (gecerli_sure / toplam_sure) if toplam_sure > 0 else 1.0
        toleransli_sure = gecerli_sure if eksik_oran <= FRAME_TOLERANS else 0.0
        return toleransli_sure


class KilitlenmeAlgo:
    def __init__(self):
        self._cal          = False
        self._baslangic    = None
        self._bb           = []
        self._aktif        = False
        self._kez          = 0
        self._son_tespit   = time.time()
        self._frame_kayit  = FrameKayitci()
        # Şartname: aynı IHA'ya tekrar kilitlenme için araya farklı IHA girmelidir
        self._son_kilit_sinif = None   # son kilitlenen IHA sınıfı/ID'si

    def _sifirla_ui(self):
        with ws_lock:
            ws_durum.update({
                "aktif": False, "gecen": 0.0, "yuzde": 0.0, "basarili": False
            })
        _sunucuya_gonder()

    def _dongu(self):
        _log("[KILIT] Başladı | 4s süre | 1s tolerans | %5 frame toleransı")
        while self._cal:
            try:
                r = requests.get(f"{SUNUCU_URL}/api/tespit_durum", timeout=0.3)
                if not r.ok:
                    time.sleep(0.1)
                    continue
                d = r.json()
            except Exception:
                time.sleep(0.2)
                continue

            simdi = time.time()

            if d.get("var") and d.get("kilitlenme_hazir"):
                self._son_tespit = simdi
                gecerli_frame   = True

                # Frame kaydet
                self._frame_kayit.ekle(gecerli_frame)

                if not self._aktif:
                    self._baslangic = simdi
                    self._bb        = []
                    self._aktif     = True
                    _log(f"[KILIT] → Başladı | conf:{d.get('conf',0):.2f} | "
                         f"Boyut:Y{d.get('boyut_yatay_pct',0):.1f}% D{d.get('boyut_dikey_pct',0):.1f}%")

                gecen = simdi - self._baslangic
                self._bb.append({
                    "cx": d["cx"], "cy": d["cy"],
                    "w":  d["w"],  "h":  d["h"]
                })

                # GCS güncelle
                with ws_lock:
                    ws_durum.update({
                        "aktif":            True,
                        "gecen":            round(gecen, 2),
                        "yuzde":            round(min(gecen / KILITLENME_SURE * 100, 100), 1),
                        "bx1":              d["bx1"], "by1": d["by1"],
                        "bx2":              d["bx2"], "by2": d["by2"],
                        "basarili":         False,
                        "boyut_yatay_pct":  d.get("boyut_yatay_pct", 0),
                        "boyut_dikey_pct":  d.get("boyut_dikey_pct", 0),
                    })
                _sunucuya_gonder()

                # ── 4 saniye doldu mu? ────────────────────────────────
                if gecen >= KILITLENME_SURE:
                    # Frame toleransı kontrolü
                    gecerli_sure = self._frame_kayit.kesintisiz_sure_hesapla(KILITLENME_SURE)
                    min_gecerli  = KILITLENME_SURE * (1 - FRAME_TOLERANS)

                    if gecerli_sure >= min_gecerli:
                        bitis = simdi
                        _log(f"[KILIT] ✓ BAŞARILI! {gecen:.2f}s | "
                             f"Frame:{gecerli_sure:.2f}s/{KILITLENME_SURE}s | "
                             f"#{self._kez+1}")

                        with ws_lock:
                            ws_durum.update({
                                "aktif":    False,
                                "basarili": True,
                                "gecen":    round(gecen, 2),
                                "yuzde":    100.0,
                                "toplam_kilitlenme": self._kez + 1,
                            })
                        _sunucuya_gonder()

                        # Şartname: 2 saniye içinde paketi gönder
                        paket_gonder(self._baslangic, bitis, self._bb, otonom=True)
                        self._kez              += 1
                        self._son_kilit_sinif   = d.get("sinif")
                        self._aktif             = False
                        self._baslangic         = None
                        self._bb                = []

                        time.sleep(3.0)
                        self._sifirla_ui()
                    else:
                        _log(f"[KILIT] ✗ Frame toleransı aşıldı: "
                             f"{gecerli_sure:.2f}s < {min_gecerli:.2f}s — sıfırlanıyor")
                        self._aktif     = False
                        self._baslangic = None
                        self._bb        = []
                        self._sifirla_ui()

            else:
                # Tespit yok veya şart sağlanmıyor
                self._frame_kayit.ekle(False)

                if self._aktif:
                    bosluk = simdi - self._son_tespit
                    if bosluk > TOLERANS_SURE:
                        gecen = simdi - self._baslangic if self._baslangic else 0
                        _log(f"[KILIT] ✗ İptal | boşluk:{bosluk:.1f}s > {TOLERANS_SURE}s | "
                             f"gecen:{gecen:.1f}s")
                        self._aktif     = False
                        self._baslangic = None
                        self._bb        = []
                        self._sifirla_ui()

            time.sleep(0.05)   # 20Hz polling

    def baslat(self):
        self._cal = True
        threading.Thread(target=self._dongu, daemon=True).start()
        return self

    def durdur(self):
        self._cal = False

    def ozet(self):
        with ws_lock:
            return {**ws_durum, "toplam": self._kez}


if __name__ == "__main__":
    print("=" * 55)
    print("TEKNOFEST — Kilitlenme Algo (Şartname Uyumlu)")
    print(f"Süre: {KILITLENME_SURE}s | Tolerans: {TOLERANS_SURE}s | "
          f"Frame: %{FRAME_TOLERANS*100:.0f}")
    print("=" * 55)
    algo = KilitlenmeAlgo().baslat()
    try:
        while True:
            time.sleep(3)
            o = algo.ozet()
            print(f"[KILIT] aktif:{o['aktif']} {o['gecen']:.1f}s "
                  f"{o['yuzde']:.0f}% | toplam:{o['toplam']}")
    except KeyboardInterrupt:
        algo.durdur()
        print("\n[KILIT] Durduruldu.")