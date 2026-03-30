from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import uvicorn

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

@app.post("/api/telemetri_gonder")
async def telemetri(request: Request):
    veri = await request.json()
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

@app.get("/api/hss_koordinatlari")
async def hss():
    return {
        "sunucusaati": sunucu_saati(),
        "hss_koordinat_bilgileri": [
            {"id": 0, "hssEnlem": 47.400, "hssBoylam": 8.550, "hssYaricap": 50}
        ]
    }

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