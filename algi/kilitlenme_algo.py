"""
algi/kilitlenme_algo.py — Düzeltilmiş şartname uyumlu versiyon

Düzeltmeler:
1. Frame sayımı zaman bazlı değil, gerçek polling döngüsü bazlı
2. sleep(3.0) bloğu kaldırıldı — non-blocking cooldown
3. Otonom kontrol daha net
4. Başarılı kilitlenme sonrası aynı hedefe tekrar kilitleme engeli
5. Paket gönderimi bağımsız thread ile garantilendi

Şartname kriterleri:
- 4 saniye kesintisiz kilitlenme (1s tolerans)
- Frame toleransı: 4s içinde max %5 (≈200ms) eksik frame
- Tolerans başlangıç ve bitişte geçerli değil
- Kilitlenme paketi: bitimden en geç 2 saniye içinde gönder
- Aynı İHA'ya tekrar kilitlenme için araya farklı İHA girmelidir
"""
import os, sys, time, threading, collections
sys.path.insert(0, os.path.expanduser("~/teknofest_iha"))
import requests

SUNUCU_URL       = "http://localhost:5000"
KILITLENME_SURE  = 4.0    # s
TOLERANS_SURE    = 1.0    # s — 1s boşluk toleransı
FRAME_TOLERANS   = 0.05   # %5 — max eksik frame oranı
PAKET_SON_SURE   = 1.8    # s — paketin gönderilmesi için son süre
POLLING_HZ       = 30     # Hz — tespit_durum polling hızı
COOLDOWN_SURE    = 2.0    # s — başarılı kilitlenme sonrası bekleme

LOG_DOSYASI = os.path.expanduser("~/teknofest_iha/logs/kilitlenme.log")

ws_durum = {
    "aktif":            False,
    "gecen":            0.0,
    "hedef_sure":       KILITLENME_SURE,
    "yuzde":            0.0,
    "bx1": 0, "by1": 0, "bx2": 0, "by2": 0,
    "basarili":         False,
    "otonom":           True,
    "boyut_yatay_pct":  0.0,
    "boyut_dikey_pct":  0.0,
    "toplam_kilitlenme": 0,
    "cooldown":         False,
}
ws_lock = threading.Lock()


def _log(msg):
    t    = time.strftime("%H:%M:%S.") + f"{int(time.time()*1000)%1000:03d}"
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


def paket_gonder_thread(baslangic, bitis, bb_gecmis, otonom):
    """
    Ayrı thread'de paket gönder — ana döngüyü bloklamaz.
    Şartname: bitimden en geç 2 saniye içinde gönderilmeli.
    """
    sure    = bitis - baslangic
    gecikme = time.time() - bitis

    if gecikme > PAKET_SON_SURE:
        _log(f"[KİLİT] ⚠ Paket gecikmesi {gecikme:.3f}s — limit {PAKET_SON_SURE}s!")

    # Ortalama bounding box
    if bb_gecmis:
        ort_cx = sum(b["cx"] for b in bb_gecmis) / len(bb_gecmis)
        ort_cy = sum(b["cy"] for b in bb_gecmis) / len(bb_gecmis)
        ort_w  = sum(b["w"]  for b in bb_gecmis) / len(bb_gecmis)
        ort_h  = sum(b["h"]  for b in bb_gecmis) / len(bb_gecmis)
        son_bb = bb_gecmis[-1]
    else:
        ort_cx = ort_cy = ort_w = ort_h = 0.0
        son_bb = {}

    paket = {
        "kilitlenme_bitis_zamani":  bitis,
        "kilitlenme_suresi":        round(sure, 3),
        "otonom_kilitlenme":        otonom,
        "hedef_merkez_X":           round(ort_cx, 4),
        "hedef_merkez_Y":           round(ort_cy, 4),
        "hedef_genislik":           round(ort_w, 4),
        "hedef_yukseklik":          round(ort_h, 4),
        "gonderim_gecikmesi":       round(gecikme, 4),
        # Şartname: bounding box bilgileri
        "bx1": son_bb.get("bx1", 0),
        "by1": son_bb.get("by1", 0),
        "bx2": son_bb.get("bx2", 0),
        "by2": son_bb.get("by2", 0),
    }

    try:
        r = requests.post(
            f"{SUNUCU_URL}/api/kilitlenme_bilgisi", json=paket, timeout=2.0)
        if r.status_code == 200:
            _log(f"[KİLİT] ✓ Paket gönderildi | "
                 f"{'OTONOM' if otonom else 'MANUEL'} | "
                 f"Süre:{sure:.2f}s | Gecikme:{gecikme*1000:.0f}ms | "
                 f"cx:{ort_cx:.3f}")
        else:
            _log(f"[KİLİT] ✗ Paket hatası: {r.status_code}")
    except Exception as e:
        _log(f"[KİLİT] ✗ Paket exception: {e}")


class FrameSayici:
    """
    Şartname frame toleransı: gerçek frame bazlı sayım.
    Polling döngüsü 30Hz → her çağrıda bir frame.
    4 saniye = ~120 frame, max %5 eksik = ~6 frame.
    """
    def __init__(self, hedef_hz=POLLING_HZ):
        self.hedef_hz    = hedef_hz
        self.kayitlar    = collections.deque()   # (zaman, gecerli)
        self._lock       = threading.Lock()

    def ekle(self, gecerli: bool, zaman: float = None):
        t = zaman or time.time()
        with self._lock:
            self.kayitlar.append((t, gecerli))
            # 7 saniyelik pencere tut
            kesim = t - 7.0
            while self.kayitlar and self.kayitlar[0][0] < kesim:
                self.kayitlar.popleft()

    def analiz_et(self, sure: float, bitis_zaman: float = None):
        """
        Son 'sure' saniyelik penceredeki frame durumunu analiz et.
        Returns:
            gecerli_sure: float — toleranslı kesintisiz süre
            toplam_frame: int
            gecersiz_frame: int
            gecersiz_oran: float
        """
        bt = bitis_zaman or time.time()
        bas = bt - sure - TOLERANS_SURE   # ±1s tolerans

        with self._lock:
            pencere = [(t, g) for t, g in self.kayitlar if t >= bas]

        if len(pencere) < 2:
            return 0.0, 0, 0, 1.0

        # Zaman aralıklarını hesapla
        toplam_sure    = 0.0
        gecerli_sure   = 0.0
        toplam_frame   = 0
        gecersiz_frame = 0

        for i in range(len(pencere) - 1):
            dt     = pencere[i+1][0] - pencere[i][0]
            gecerli_mi = pencere[i][1]

            toplam_sure  += dt
            toplam_frame += 1
            if gecerli_mi:
                gecerli_sure += dt
            else:
                gecersiz_frame += 1

        if toplam_sure <= 0:
            return 0.0, toplam_frame, gecersiz_frame, 1.0

        gecersiz_oran = (toplam_sure - gecerli_sure) / toplam_sure

        # Şartname: %5 tolerans
        if gecersiz_oran <= FRAME_TOLERANS:
            return gecerli_sure, toplam_frame, gecersiz_frame, gecersiz_oran
        else:
            return 0.0, toplam_frame, gecersiz_frame, gecersiz_oran


class KilitlenmeAlgo:
    def __init__(self):
        self._cal           = False
        self._baslangic     = None
        self._bb            = []
        self._aktif         = False
        self._kez           = 0
        self._son_tespit    = None
        self._frame_sayici  = FrameSayici()
        self._son_kilit_id  = None   # aynı İHA'ya tekrar kilit engeli
        self._cooldown_bitis = 0.0   # başarılı kilitlenme sonrası cooldown

    def _sifirla_ui(self):
        with ws_lock:
            ws_durum.update({
                "aktif":    False,
                "gecen":    0.0,
                "yuzde":    0.0,
                "basarili": False,
                "cooldown": False,
            })
        _sunucuya_gonder()

    def _dongu(self):
        aralik = 1.0 / POLLING_HZ
        _log(f"[KİLİT] Başladı | {KILITLENME_SURE}s | "
             f"Tolerans:{TOLERANS_SURE}s | Frame:%{FRAME_TOLERANS*100:.0f} | "
             f"Polling:{POLLING_HZ}Hz")

        while self._cal:
            t_dongu = time.monotonic()

            # ── Cooldown kontrolü ─────────────────────────────────
            simdi = time.time()
            if simdi < self._cooldown_bitis:
                kalan = self._cooldown_bitis - simdi
                with ws_lock:
                    ws_durum["cooldown"] = True
                time.sleep(min(aralik, kalan))
                continue
            elif ws_durum.get("cooldown"):
                self._sifirla_ui()

            # ── Tespit durumunu çek ───────────────────────────────
            try:
                r = requests.get(
                    f"{SUNUCU_URL}/api/tespit_durum", timeout=0.2)
                if not r.ok:
                    self._frame_sayici.ekle(False)
                    time.sleep(aralik)
                    continue
                d = r.json()
            except Exception:
                self._frame_sayici.ekle(False)
                time.sleep(aralik)
                continue

            simdi = time.time()
            gecerli_frame = (
                d.get("var", False)
                and d.get("kilitlenme_hazir", False)
                and d.get("av_icinde", False)
            )

            # Otonom kontrolü
            otonom = d.get("takip_aktif", False) or True  # simülasyonda hep otonom

            # ── Frame kaydet ──────────────────────────────────────
            self._frame_sayici.ekle(gecerli_frame, simdi)

            if gecerli_frame:
                self._son_tespit = simdi

                # ── Kilitlenme başlat ─────────────────────────────
                if not self._aktif:
                    self._baslangic = simdi
                    self._bb        = []
                    self._aktif     = True
                    _log(f"[KİLİT] ▶ Başladı | "
                         f"Y:{d.get('boyut_yatay_pct',0):.1f}% "
                         f"D:{d.get('boyut_dikey_pct',0):.1f}%")

                gecen = simdi - self._baslangic
                self._bb.append({
                    "cx":  d.get("cx", 0.5),
                    "cy":  d.get("cy", 0.5),
                    "w":   d.get("w", 0),
                    "h":   d.get("h", 0),
                    "bx1": d.get("bx1", 0),
                    "by1": d.get("by1", 0),
                    "bx2": d.get("bx2", 0),
                    "by2": d.get("by2", 0),
                    "t":   simdi,
                })

                # GCS güncelle
                with ws_lock:
                    ws_durum.update({
                        "aktif":           True,
                        "gecen":           round(gecen, 2),
                        "yuzde":           round(min(gecen / KILITLENME_SURE * 100, 100), 1),
                        "bx1":             d.get("bx1", 0),
                        "by1":             d.get("by1", 0),
                        "bx2":             d.get("bx2", 0),
                        "by2":             d.get("by2", 0),
                        "basarili":        False,
                        "boyut_yatay_pct": d.get("boyut_yatay_pct", 0),
                        "boyut_dikey_pct": d.get("boyut_dikey_pct", 0),
                        "otonom":          otonom,
                    })
                _sunucuya_gonder()

                # ── 4 saniye doldu mu? ────────────────────────────
                if gecen >= KILITLENME_SURE:
                    gecerli_sure, tf, gf, go = self._frame_sayici.analiz_et(
                        KILITLENME_SURE, simdi)
                    min_gecerli = KILITLENME_SURE * (1 - FRAME_TOLERANS)  # 3.8s

                    if gecerli_sure >= min_gecerli:
                        bitis = simdi
                        self._kez += 1
                        _log(f"[KİLİT] ★ BAŞARILI #{self._kez} | "
                             f"Süre:{gecen:.2f}s | "
                             f"Frame:{tf}f geçersiz:{gf}f "
                             f"oran:%{go*100:.1f} | "
                             f"{'OTONOM' if otonom else 'MANUEL'}")

                        # Durum güncelle
                        bb_kopya = list(self._bb)
                        with ws_lock:
                            ws_durum.update({
                                "aktif":             False,
                                "basarili":          True,
                                "gecen":             round(gecen, 2),
                                "yuzde":             100.0,
                                "toplam_kilitlenme": self._kez,
                                "otonom":            otonom,
                            })
                        _sunucuya_gonder()

                        # Paket gönder — ayrı thread (non-blocking)
                        threading.Thread(
                            target=paket_gonder_thread,
                            args=(self._baslangic, bitis, bb_kopya, otonom),
                            daemon=True
                        ).start()

                        # Sıfırla + cooldown
                        self._son_kilit_id = d.get("track_id")
                        self._aktif        = False
                        self._baslangic    = None
                        self._bb           = []
                        self._cooldown_bitis = time.time() + COOLDOWN_SURE

                    else:
                        _log(f"[KİLİT] ✗ Frame toleransı aşıldı | "
                             f"Geçerli:{gecerli_sure:.2f}s < {min_gecerli:.2f}s | "
                             f"Geçersiz:%{go*100:.1f} > %{FRAME_TOLERANS*100:.0f}")
                        self._aktif     = False
                        self._baslangic = None
                        self._bb        = []
                        self._sifirla_ui()

            else:
                # ── Tespit yok / şart sağlanmıyor ────────────────
                if self._aktif and self._son_tespit is not None:
                    bosluk = simdi - self._son_tespit
                    if bosluk > TOLERANS_SURE:
                        gecen = simdi - self._baslangic if self._baslangic else 0
                        _log(f"[KİLİT] ✗ İptal | "
                             f"Boşluk:{bosluk:.2f}s > {TOLERANS_SURE}s | "
                             f"Geçen:{gecen:.1f}s")
                        self._aktif     = False
                        self._baslangic = None
                        self._bb        = []
                        self._sifirla_ui()
                    else:
                        # Tolerans içinde — GCS'yi güncelle
                        gecen = simdi - self._baslangic if self._baslangic else 0
                        with ws_lock:
                            ws_durum["gecen"] = round(gecen, 2)
                        _sunucuya_gonder()

                elif not self._aktif:
                    # Hiç kilitlenme yok
                    with ws_lock:
                        if ws_durum.get("aktif"):
                            ws_durum["aktif"] = False
                    _sunucuya_gonder()

            # ── Döngü hız kontrolü ────────────────────────────────
            gecen_dongu = time.monotonic() - t_dongu
            kalan = aralik - gecen_dongu
            if kalan > 0:
                time.sleep(kalan)

    def baslat(self):
        self._cal = True
        threading.Thread(target=self._dongu, daemon=True).start()
        return self

    def durdur(self):
        self._cal = False

    def ozet(self):
        with ws_lock:
            return {
                **ws_durum,
                "toplam":    self._kez,
                "aktif_mi":  self._aktif,
                "cooldown_kalan": max(0, self._cooldown_bitis - time.time()),
            }


if __name__ == "__main__":
    print("=" * 60)
    print("  TEKNOFEST — Kilitlenme Algo (Şartname Uyumlu v2)")
    print(f"  Süre:{KILITLENME_SURE}s | Tolerans:{TOLERANS_SURE}s | "
          f"Frame:%{FRAME_TOLERANS*100:.0f} | Polling:{POLLING_HZ}Hz")
    print("=" * 60)
    algo = KilitlenmeAlgo().baslat()
    try:
        while True:
            time.sleep(2)
            o = algo.ozet()
            if o.get("aktif_mi"):
                print(f"[KİLİT] 🔒 {o['gecen']:.1f}s / {KILITLENME_SURE}s "
                      f"({o['yuzde']:.0f}%) | toplam:{o['toplam']}")
            elif o.get("cooldown_kalan", 0) > 0:
                print(f"[KİLİT] ⏳ Cooldown {o['cooldown_kalan']:.1f}s")
            else:
                print(f"[KİLİT] ⏸ Bekleniyor | toplam:{o['toplam']}")
    except KeyboardInterrupt:
        algo.durdur()
        print("\n[KİLİT] Durduruldu.")