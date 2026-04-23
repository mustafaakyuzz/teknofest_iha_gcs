from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from datetime import datetime
import uvicorn

# YENİ: Swagger arayüzü için HSS tetikleme modeli
class HSSTestDurumu(BaseModel):
    aktif: bool

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

aktif_session = set()

# Kilitlenme durumu — yolo_tespit + kilitlenme_algo buraya yazar
# GCS polling ile okur
kilitlenme_durum = {
    "aktif": False,
    "gecen": 0.0,
    "hedef_sure": 4.0,
    "yuzde": 0.0,
    "bx1": 0, "by1": 0, "bx2": 0, "by2": 0,
    "basarili": False,
    "otonom": True,
    "var": False,
    "conf": 0.0,
    "cx": 0.0, "cy": 0.0,
    "w": 0.0, "h": 0.0,
    "av_icinde": False,
    "alan_ok": False,
    "kilitlenme_hazir": False,
    "takip_aktif": False
}

def sunucu_saati():
    simdi = datetime.utcnow()
    return {
        "gun": simdi.day,
        "saat": simdi.hour,
        "dakika": simdi.minute,
        "saniye": simdi.second,
        "milisaniye": simdi.microsecond // 1000
    }

@app.post("/api/giris")
async def giris(request: Request):
    veri = await request.json()
    print(f"[GIRIS] kadi={veri.get('kadi')}")
    aktif_session.add(veri.get("kadi"))
    return Response(content="1", status_code=200)

@app.get("/api/sunucusaati")
async def saat():
    return sunucu_saati()

son_telemetri = {}

@app.post("/api/telemetri_gonder")
async def telemetri(request: Request):
    global son_telemetri
    veri = await request.json()
    
    # YENİ EKLENEN: Gerçek PX4 telemetrisini GCS haritasında göstermek için kaydet
    if veri.get("takim_numarasi") == 1:
        son_telemetri = veri
        
    print(
        f"[TELEMETRI] "
        f"enlem={veri.get('iha_enlem', 0):.6f} "
        f"irtifa={veri.get('iha_irtifa')}m "
        f"hiz={veri.get('iha_hiz')}m/s "
        f"otonom={veri.get('iha_otonom')}"
    )
    return {
        "sunucusaati": sunucu_saati(),
        "konumBilgileri": [
            {
                "takim_numarasi": 99,
                "iha_enlem": 47.399,
                "iha_boylam": 8.548,
                "iha_irtifa": 80.0,
                "iha_dikilme": 0.0,
                "iha_yonelme": 180.0,
                "iha_yatis": 0.0,
                "iha_hizi": 20.0,
                "zaman_farki": 50
            }
        ]
    }

# YENİ EKLENEN: GCS arayüzünün gerçek İHA konumunu okuması için
@app.get("/api/telemetri_al")
async def telemetri_al():
    return son_telemetri

@app.post("/api/kilitlenme_bilgisi")
async def kilitlenme(request: Request):
    veri = await request.json()
    print(f"[KILITLENME] otonom={veri.get('otonom_kilitlenme')} "
          f"sure={veri.get('kilitlenme_suresi', 0):.2f}s "
          f"gecikme={veri.get('gonderim_gecikmesi', 0):.3f}s")
    return {"durum": "basarili"}

@app.post("/api/kamikaze_bilgisi")
async def kamikaze(request: Request):
    veri = await request.json()
    print(f"[KAMIKAZE] qr={veri.get('qrMetni')}")
    return {"durum": "basarili"}

@app.get("/api/qr_koordinati")
async def qr():
    return {"qrEnlem": 47.399, "qrBoylam": 8.548}

# YENİ: HSS durumunu kontrol eden global değişken (Başlangıçta kapalı)
hss_aktif = False 

@app.get("/api/hss_koordinatlari")
async def hss():
    # Şartname: HSS kapalıysa sunucu boş liste [] döndürür.
    hss_liste = []
    if hss_aktif:
        # Devriye rotanın (DEVRIYE_WP) 4 farklı kenarını kesecek zorlu bir test parkuru
        hss_liste = [
            # 1. Kuzey Kenarını Kesen (Yarıçap 40m)
            {"id": 1, "hssEnlem": 47.3985, "hssBoylam": 8.5475, "hssYaricap": 40},
            # 2. Doğu Kenarını Kesen (Yarıçap 50m)
            {"id": 2, "hssEnlem": 47.3978, "hssBoylam": 8.5488, "hssYaricap": 50},
            # 3. Güney Kenarını Kesen (Yarıçap 45m)
            {"id": 3, "hssEnlem": 47.3973, "hssBoylam": 8.5450, "hssYaricap": 45},
            # 4. Batı Kenarını Kesen (Büyük Boy - Yarıçap 65m)
            {"id": 4, "hssEnlem": 47.3980, "hssBoylam": 8.5434, "hssYaricap": 65}
        ]
        
    return {
        "sunucusaati": sunucu_saati(),
        "hss_koordinat_bilgileri": hss_liste
    }

# YENİ TEST ENDPOINT'İ: HSS'yi Swagger üzerinden açıp kapatmak için
@app.post("/api/hss_test_tetikle")
async def hss_tetikle(durum: HSSTestDurumu):
    global hss_aktif
    hss_aktif = durum.aktif
    
    mesaj = "AKTİF EDİLDİ (Kırmızı Alan Açıldı!)" if hss_aktif else "KAPATILDI (Alan Temiz)"
    print(f"\n[HAKEM SİMÜLASYONU] HSS Sistemi {mesaj}\n")
    
    return {"mesaj": f"HSS Başarıyla {mesaj}", "hss_aktif": hss_aktif}

# ── KILITLENME DURUM ENDPOINT ──
# kilitlenme_algo.py buraya POST atar, GCS polling ile okur

@app.post("/api/kilitlenme_durum")
async def kilitlenme_durum_guncelle(request: Request):
    global kilitlenme_durum
    try:
        veri = await request.json()
        kilitlenme_durum.update(veri)
    except Exception:
        pass
    return {"ok": True}

@app.get("/api/kilitlenme_durum")
async def kilitlenme_durum_al():
    return kilitlenme_durum

# ── YOLO TESPIT DURUM ──
# yolo_tespit.py buraya POST atar

tespit_durum = {
    "var": False, "conf": 0.0, "sinif": "",
    "bx1": 0, "by1": 0, "bx2": 0, "by2": 0,
    "cx": 0.0, "cy": 0.0, "w": 0.0, "h": 0.0,
    "av_icinde": False, "alan_ok": False,
    "kilitlenme_hazir": False, "takip_aktif": False,
    "zaman": 0.0
}

@app.post("/api/tespit_durum")
async def tespit_guncelle(request: Request):
    global tespit_durum
    try:
        veri = await request.json()
        tespit_durum.update(veri)
    except Exception:
        pass
    return {"ok": True}

@app.get("/api/tespit_durum")
async def tespit_al():
    return tespit_durum

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=5000)