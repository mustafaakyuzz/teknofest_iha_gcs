import requests
import time
from datetime import datetime

# Yarışma günü gerçek IP buraya gelecek
SUNUCU_URL = "http://127.0.0.1:5000"

# Takım bilgileri — yarışmadan önce doldurulacak
TAKIM_KADI = "takimkadi"
TAKIM_SIFRE = "takimsifresi"
TAKIM_NUMARASI = 1

# Session — oturum açınca cookie'yi saklar
session = requests.Session()

# ─────────────────────────────────────────
# 1. OTURUM AÇMA
# ─────────────────────────────────────────
def oturum_ac():
    """Yarışma başında bir kere çağrılır."""
    url = f"{SUNUCU_URL}/api/giris"
    veri = {
        "kadi": TAKIM_KADI,
        "sifre": TAKIM_SIFRE
    }
    try:
        yanit = session.post(url, json=veri, timeout=5)
        if yanit.status_code == 200:
            print(f"[GIRIS] Başarılı. Takım no: {yanit.text}")
            return True
        else:
            print(f"[GIRIS] Hata: {yanit.status_code} — {yanit.text}")
            return False
    except Exception as e:
        print(f"[GIRIS] Bağlantı hatası: {e}")
        return False

# ─────────────────────────────────────────
# 2. SUNUCU SAATİ
# ─────────────────────────────────────────
def sunucu_saati_al():
    """Güncel sunucu saatini döner."""
    url = f"{SUNUCU_URL}/api/sunucusaati"
    try:
        yanit = session.get(url, timeout=3)
        if yanit.status_code == 200:
            return yanit.json()
        else:
            print(f"[SAAT] Hata: {yanit.status_code}")
            return None
    except Exception as e:
        print(f"[SAAT] Bağlantı hatası: {e}")
        return None

# ─────────────────────────────────────────
# 3. TELEMETRİ GÖNDERİMİ
# ─────────────────────────────────────────
def telemetri_gonder(konum, attitude, hiz, batarya, otonom,
                     kilitlenme=0, hedef_x=0, hedef_y=0,
                     hedef_genislik=0, hedef_yukseklik=0,
                     gps_saati=None):
    """
    1-2 Hz arası çağrılmalı.
    konum: (enlem, boylam, irtifa)
    attitude: (dikilme, yonelme, yatis)
    """
    if gps_saati is None:
        simdi = datetime.utcnow()
        gps_saati = {
            "saat": simdi.hour,
            "dakika": simdi.minute,
            "saniye": simdi.second,
            "milisaniye": simdi.microsecond // 1000
        }

    url = f"{SUNUCU_URL}/api/telemetri_gonder"
    paket = {
        "takim_numarasi": TAKIM_NUMARASI,
        "iha_enlem": round(konum[0], 8),
        "iha_boylam": round(konum[1], 8),
        "iha_irtifa": round(konum[2], 2),
        "iha_dikilme": round(attitude[0], 2),     # -90 ile +90
        "iha_yonelme": round(attitude[1], 2),     # 0 ile 360
        "iha_yatis": round(attitude[2], 2),       # -90 ile +90
        "iha_hiz": round(abs(hiz), 2),            # pozitif, yönsüz
        "iha_batarya": round(batarya, 1),
        "iha_otonom": 1 if otonom else 0,
        "iha_kilitlenme": kilitlenme,
        "hedef_merkez_X": hedef_x,
        "hedef_merkez_Y": hedef_y,
        "hedef_genislik": hedef_genislik,
        "hedef_yukseklik": hedef_yukseklik,
        "gps_saati": gps_saati
    }

    try:
        yanit = session.post(url, json=paket, timeout=3)
        if yanit.status_code == 200:
            return yanit.json()  # rakip İHA konumları burada
        elif yanit.status_code == 401:
            print("[TELEMETRI] Oturum süresi dolmuş, yeniden giriş...")
            oturum_ac()
        else:
            print(f"[TELEMETRI] Hata {yanit.status_code}: {yanit.text}")
        return None
    except Exception as e:
        print(f"[TELEMETRI] Bağlantı hatası: {e}")
        return None

# ─────────────────────────────────────────
# 4. KİLİTLENME BİLGİSİ
# ─────────────────────────────────────────
def kilitlenme_gonder(bitis_saati=None, otonom=True):
    """
    Kilitlenme bitiminden sonra en geç 2 saniye içinde çağrılmalı.
    bitis_saati: sunucu saati formatında dict, None ise otomatik alınır.
    """
    if bitis_saati is None:
        bitis_saati = sunucu_saati_al()
        if bitis_saati is None:
            simdi = datetime.utcnow()
            bitis_saati = {
                "saat": simdi.hour,
                "dakika": simdi.minute,
                "saniye": simdi.second,
                "milisaniye": simdi.microsecond // 1000
            }

    url = f"{SUNUCU_URL}/api/kilitlenme_bilgisi"
    paket = {
        "kilitlenmeBitisZamani": bitis_saati,
        "otonom_kilitlenme": 1 if otonom else 0
    }

    try:
        yanit = session.post(url, json=paket, timeout=3)
        if yanit.status_code == 200:
            print(f"[KILITLENME] Gönderildi. Otonom: {otonom}")
            return True
        else:
            print(f"[KILITLENME] Hata {yanit.status_code}: {yanit.text}")
            return False
    except Exception as e:
        print(f"[KILITLENME] Bağlantı hatası: {e}")
        return False

# ─────────────────────────────────────────
# 5. KAMİKAZE BİLGİSİ
# ─────────────────────────────────────────
def kamikaze_gonder(baslangic_saati, bitis_saati, qr_metni):
    """
    Kamikaze bitiminden sonra en geç 2 saniye içinde çağrılmalı.
    """
    url = f"{SUNUCU_URL}/api/kamikaze_bilgisi"
    paket = {
        "kamikazeBaslangicZamani": baslangic_saati,
        "kamikazeBitisZamani": bitis_saati,
        "qrMetni": qr_metni
    }

    try:
        yanit = session.post(url, json=paket, timeout=3)
        if yanit.status_code == 200:
            print(f"[KAMIKAZE] Gönderildi. QR: {qr_metni}")
            return True
        else:
            print(f"[KAMIKAZE] Hata {yanit.status_code}: {yanit.text}")
            return False
    except Exception as e:
        print(f"[KAMIKAZE] Bağlantı hatası: {e}")
        return False

# ─────────────────────────────────────────
# 6. QR KOORDİNATI AL
# ─────────────────────────────────────────
def qr_koordinati_al():
    """Kamikaze hedefinin koordinatını döner."""
    url = f"{SUNUCU_URL}/api/qr_koordinati"
    try:
        yanit = session.get(url, timeout=3)
        if yanit.status_code == 200:
            veri = yanit.json()
            print(f"[QR] Konum: {veri['qrEnlem']}, {veri['qrBoylam']}")
            return veri
        else:
            print(f"[QR] Hata {yanit.status_code}")
            return None
    except Exception as e:
        print(f"[QR] Bağlantı hatası: {e}")
        return None

# ─────────────────────────────────────────
# 7. HSS KOORDİNATLARI AL
# ─────────────────────────────────────────
def hss_koordinatlari_al():
    """
    Aktif HSS bölgelerini döner.
    Hakem duyurusu olmadan boş liste gelir.
    """
    url = f"{SUNUCU_URL}/api/hss_koordinatlari"
    try:
        yanit = session.get(url, timeout=3)
        if yanit.status_code == 200:
            veri = yanit.json()
            bolgeler = veri.get("hss_koordinat_bilgileri", [])
            if bolgeler:
                print(f"[HSS] {len(bolgeler)} aktif bölge var!")
            return bolgeler
        else:
            print(f"[HSS] Hata {yanit.status_code}")
            return []
    except Exception as e:
        print(f"[HSS] Bağlantı hatası: {e}")
        return []