import asyncio
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

async def baglan():
    drone = System()
    await drone.connect(system_address="udpin://0.0.0.0:14540")
    
    print("Bağlantı bekleniyor...")
    async for state in drone.core.connection_state():
        if state.is_connected:
            print("PX4 bağlandı.")
            break

    print("GPS kilidi bekleniyor...")
    async for health in drone.telemetry.health():
        if health.is_global_position_ok and health.is_home_position_ok:
            print("GPS hazır.")
            break
    
    return drone

async def mevcut_konum_al(drone):
    async for konum in drone.telemetry.position():
        return konum

async def waypoint_ucusu(drone):
    baslangic = await mevcut_konum_al(drone)
    lat = baslangic.latitude_deg
    lon = baslangic.longitude_deg
    
    print(f"Başlangıç konumu: {lat:.6f}, {lon:.6f}")
    
    gorev_noktalari = [
        MissionItem(
            latitude_deg=lat + 0.001,
            longitude_deg=lon,
            relative_altitude_m=100,
            speed_m_s=15,
            is_fly_through=True,
            gimbal_pitch_deg=float('nan'),
            gimbal_yaw_deg=float('nan'),
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=float('nan'),
            camera_photo_interval_s=float('nan'),
            acceptance_radius_m=10,
            yaw_deg=float('nan'),
            camera_photo_distance_m=float('nan'),
            vehicle_action=MissionItem.VehicleAction.NONE
        ),
        MissionItem(
            latitude_deg=lat + 0.001,
            longitude_deg=lon + 0.001,
            relative_altitude_m=100,
            speed_m_s=15,
            is_fly_through=True,
            gimbal_pitch_deg=float('nan'),
            gimbal_yaw_deg=float('nan'),
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=float('nan'),
            camera_photo_interval_s=float('nan'),
            acceptance_radius_m=10,
            yaw_deg=float('nan'),
            camera_photo_distance_m=float('nan'),
            vehicle_action=MissionItem.VehicleAction.NONE
        ),
        MissionItem(
            latitude_deg=lat,
            longitude_deg=lon,
            relative_altitude_m=80,
            speed_m_s=15,
            is_fly_through=False,
            gimbal_pitch_deg=float('nan'),
            gimbal_yaw_deg=float('nan'),
            camera_action=MissionItem.CameraAction.NONE,
            loiter_time_s=float('nan'),
            camera_photo_interval_s=float('nan'),
            acceptance_radius_m=10,
            yaw_deg=float('nan'),
            camera_photo_distance_m=float('nan'),
            vehicle_action=MissionItem.VehicleAction.NONE
        ),
    ]
    
    gorev_plani = MissionPlan(gorev_noktalari)
    
    print("Görev yükleniyor...")
    await drone.mission.set_return_to_launch_after_mission(True)
    await drone.mission.upload_mission(gorev_plani)
    
    print("Arm ediliyor...")
    await drone.action.arm()
    await asyncio.sleep(2)

    print("Kalkış...")
    await drone.action.takeoff()
    
    print("İrtifa bekleniyor...")
    async for konum in drone.telemetry.position():
        if konum.relative_altitude_m > 30:
            print(f"İrtifa yeterli: {konum.relative_altitude_m:.1f}m")
            break
    
    print("Görev başlatılıyor...")
    await drone.mission.start_mission()
    
    # Mission progress yerine süre bazlı bekle + konum yazdır
    print("Rota izleniyor... (60 saniye)")
    for i in range(60):
        await asyncio.sleep(1)
        konum = await mevcut_konum_al(drone)
        print(f"[{i+1:02d}s] Lat: {konum.latitude_deg:.6f} "
              f"Lon: {konum.longitude_deg:.6f} "
              f"Alt: {konum.relative_altitude_m:.1f}m")
    
    print("İniş...")
    await drone.action.land()
    print("Görev tamamlandı.")

async def main():
    print("Script başladı...")
    drone = await baglan()
    print("Drone hazır, görev başlıyor...")
    await waypoint_ucusu(drone)

asyncio.run(main())