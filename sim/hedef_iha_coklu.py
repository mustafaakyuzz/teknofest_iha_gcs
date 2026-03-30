"""
sim/hedef_iha_coklu.py — 3 IHA, hafif versiyon
subprocess overhead minimuma indirildi:
- 3 IHA (5'ten az)
- 8Hz güncelleme (20'den az)  
- timeout=50ms (300ms'den az)
- Her IHA kendi thread'inde ama sleep ile throttle edilmiş
"""
import os, time, math, threading, subprocess
os.environ["PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION"] = "python"

SDF_DOSYA = os.path.expanduser("~/teknofest_iha/sim/hedef_cessna.sdf")

# 3 IHA — devriye alanının 3 köşesine yerleştirilmiş
# Devriye: X[-156,55] Y[-52,81]
IHALAR = [
    # (isim,        merkez_x, merkez_y,  z,    yaricap, faz_aci,   hiz)
    ("hedef_iha_1", -110.0,   65.0,     60.0,  8.0,   0.0,        5.0),
    ("hedef_iha_2",  -50.0,  -38.0,     60.0,  8.0,   math.pi,    5.0),
    ("hedef_iha_3",   30.0,   20.0,     60.0,  8.0,   math.pi/2,  5.0),
]

GUNCELLEME_HZ = 8   # Düşük frekans — subprocess için yeterli


def set_pose(model_adi, x, y, z, yaw):
    cy, sy = math.cos(yaw * 0.5), math.sin(yaw * 0.5)
    req = (f'name: "{model_adi}" '
           f'position: {{x: {x:.2f}, y: {y:.2f}, z: {z:.2f}}} '
           f'orientation: {{x: 0.0, y: 0.0, z: {sy:.4f}, w: {cy:.4f}}}')
    try:
        subprocess.run(
            ["gz", "service", "-s", "/world/default/set_pose",
             "--reqtype", "gz.msgs.Pose",
             "--reptype", "gz.msgs.Boolean",
             "--timeout", "50",   # 50ms — hızlı timeout, bloke etme
             "--req", req],
            capture_output=True, timeout=0.2   # 200ms max
        )
    except Exception:
        pass


def spawn_iha(model_adi, bx, by, bz):
    subprocess.run([
        "gz", "service", "-s", "/world/default/remove",
        "--reqtype", "gz.msgs.Entity", "--reptype", "gz.msgs.Boolean",
        "--timeout", "1500", "--req", f'name: "{model_adi}" type: 2'
    ], capture_output=True, timeout=4)
    time.sleep(1.5)

    r = subprocess.run([
        "gz", "service", "-s", "/world/default/create",
        "--reqtype", "gz.msgs.EntityFactory", "--reptype", "gz.msgs.Boolean",
        "--timeout", "8000", "--req",
        f'sdf_filename: "{SDF_DOSYA}" name: "{model_adi}" '
        f'pose: {{position: {{x: {bx:.1f}, y: {by:.1f}, z: {bz:.1f}}}}}'
    ], capture_output=True, text=True, timeout=12)
    ok = "true" in r.stdout or r.returncode == 0
    print(f"  {'✓' if ok else '✗'} {model_adi} @ ({bx:.0f},{by:.0f},{bz:.0f})")
    return ok


def iha_dongu(model_adi, mx, my, mz, yaricap, faz, hiz):
    dt          = 1.0 / GUNCELLEME_HZ
    aciksal_hiz = hiz / yaricap
    aci         = faz

    while True:
        t0  = time.monotonic()
        aci -= aciksal_hiz * dt

        x   = mx + yaricap * math.cos(aci)
        y   = my + yaricap * math.sin(aci)
        yaw = math.atan2(-yaricap * math.cos(aci), yaricap * math.sin(aci))

        set_pose(model_adi, x, y, mz, yaw)

        gecen = time.monotonic() - t0
        kalan = dt - gecen
        if kalan > 0:
            time.sleep(kalan)


if __name__ == "__main__":
    print("=" * 50)
    print(f"  TEKNOFEST 2026 — {len(IHALAR)} Hedef IHA (hafif)")
    print(f"  {GUNCELLEME_HZ}Hz | 15m daire | 60m | 5m/s")
    print("=" * 50)

    print("\n[HEDEF] Spawn ediliyor...")
    for cfg in IHALAR:
        model_adi, mx, my, mz, yaricap, faz, hiz = cfg
        bx = mx + yaricap * math.cos(faz)
        by = my + yaricap * math.sin(faz)
        spawn_iha(model_adi, bx, by, mz)
        time.sleep(2.0)

    print(f"\n[HEDEF] 3s bekleniyor...")
    time.sleep(3.0)

    print("[HEDEF] Hareket başlıyor...")
    for cfg in IHALAR:
        model_adi, mx, my, mz, yaricap, faz, hiz = cfg
        threading.Thread(
            target=iha_dongu,
            args=(model_adi, mx, my, mz, yaricap, faz, hiz),
            daemon=True
        ).start()
        print(f"  ✓ {model_adi}")

    print(f"\n[HEDEF] Aktif! Ctrl+C durdurur.\n")
    try:
        while True:
            time.sleep(15.0)
            print(f"[HEDEF] 3 IHA çalışıyor...")
    except KeyboardInterrupt:
        print("\n[HEDEF] Durduruldu.")