import asyncio
import math
import sys
sys.path.append('/home/mustafa/teknofest_iha')

from mavsdk import System
from api.sunucu_iletisim import oturum_ac, telemetri_gonder
from db.models import SessionLocal, Telemetri, RakipKonum, veritabani_olustur

async def telemetri_dongusu_baslat():
    # Veritabanı hazır mı kontrol et
    veritabani_olustur()

    drone = System()
    await drone.connect(system_address="udpin://0.0.0.0:14540")

    print("PX4 bağlantısı bekleniyor...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("Bağlandı.")
            break

    # Oturum aç
    oturum_ac()

    print("Telemetri döngüsü başladı (1 Hz)...")

    while True:
        try:
            # PX4'ten verileri al
            konum    = await drone.telemetry.position().__anext__()
            attitude = await drone.telemetry.attitude_euler().__anext__()
            hiz_obj  = await drone.telemetry.velocity_ned().__anext__()
            ucus_modu = await drone.telemetry.flight_mode().__anext__()
            batarya  = await drone.telemetry.battery().__anext__()

            hiz = math.sqrt(
                hiz_obj.north_m_s**2 +
                hiz_obj.east_m_s**2 +
                hiz_obj.down_m_s**2
            )

            otonom = str(ucus_modu) in [
                "FlightMode.MISSION",
                "FlightMode.AUTO_LOITER",
                "FlightMode.TAKEOFF",
                "FlightMode.LAND"
            ]

            batarya_yuzde = (batarya.remaining_percent * 100
                             if batarya.remaining_percent else 99.0)

            # Terminale yazdır
            print(
                f"Enlem: {konum.latitude_deg:.6f} | "
                f"Boylam: {konum.longitude_deg:.6f} | "
                f"İrtifa: {konum.relative_altitude_m:.1f}m | "
                f"Hız: {hiz:.1f}m/s | "
                f"Otonom: {otonom}"
            )

            # Sunucuya gönder
            yanit = telemetri_gonder(
                konum=(konum.latitude_deg,
                       konum.longitude_deg,
                       konum.relative_altitude_m),
                attitude=(attitude.pitch_deg,
                          attitude.yaw_deg,
                          attitude.roll_deg),
                hiz=hiz,
                batarya=batarya_yuzde,
                otonom=otonom
            )

            # Veritabanına kaydet
            db = SessionLocal()
            try:
                # Kendi telemetrimizi kaydet
                kayit = Telemetri(
                    enlem=konum.latitude_deg,
                    boylam=konum.longitude_deg,
                    irtifa=konum.relative_altitude_m,
                    dikilme=attitude.pitch_deg,
                    yonelme=attitude.yaw_deg,
                    yatis=attitude.roll_deg,
                    hiz=hiz,
                    batarya=batarya_yuzde,
                    otonom=otonom
                )
                db.add(kayit)

                # Rakip konumlarını kaydet
                if yanit and "konumBilgileri" in yanit:
                    rakipler = yanit["konumBilgileri"]
                    print(f"Rakip sayısı: {len(rakipler)}")
                    for rakip in rakipler:
                        rakip_kayit = RakipKonum(
                            takim_no=rakip.get("takim_numarasi"),
                            enlem=rakip.get("iha_enlem"),
                            boylam=rakip.get("iha_boylam"),
                            irtifa=rakip.get("iha_irtifa"),
                            hiz=rakip.get("iha_hizi"),
                            zaman_farki=rakip.get("zaman_farki")
                        )
                        db.add(rakip_kayit)

                db.commit()

            except Exception as db_hata:
                print(f"[DB] Kayıt hatası: {db_hata}")
                db.rollback()
            finally:
                db.close()

        except Exception as e:
            print(f"Telemetri hatası: {e}")

        await asyncio.sleep(1)

asyncio.run(telemetri_dongusu_baslat())