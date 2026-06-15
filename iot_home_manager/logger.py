import asyncio
import csv
import os
from datetime import datetime
from fastapi import FastAPI
from iot_home_manager.config import POLLING_INTERVAL

def get_daily_filename() -> str:
    current_date = datetime.now().strftime("%Y-%m-%d")
    os.makedirs("logs", exist_ok=True)
    return f"logs/log_{current_date}.csv"

def initialize_csv(filename: str):
    # Ensure directory is created in case it was called directly
    dirname = os.path.dirname(filename)
    if dirname:
        os.makedirs(dirname, exist_ok=True)
    if not os.path.exists(filename):
        with open(filename, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow([
                "Timestamp", "Device", "Status", 
                "Ambient_Temp_C", "Target_Temp_C", 
                "Mode", "Fan_Speed", 
                "Hourly_Consumption_kWh", "CO2_ppm"
            ])
        print(f"[System] New daily log file '{filename}' initialized.")

async def run_unified_logging(app: FastAPI):
    air_conditioners = app.state.mitsubishi_devices
    current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    current_csv = get_daily_filename()
    
    initialize_csv(current_csv)
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Starting automatic logging cycle...")
    
    with open(current_csv, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        
        for device in air_conditioners:
            try:
                await device.update()
                
                status = "ON" if device.power else "OFF"
                temp_amb = device.room_temperature
                temp_tar = device.target_temperature
                mode = device.operation_mode
                fan = device.fan_speed
                
                current_total_energy = getattr(device, "total_energy_consumed", 0.0)
                previous_total_energy = app.state.energy_history.get(device.name, None)
                
                if previous_total_energy is None:
                    hourly_delta = 0.0
                else:
                    hourly_delta = round(current_total_energy - previous_total_energy, 3)
                    if hourly_delta < 0:
                        hourly_delta = 0.0
                
                app.state.energy_history[device.name] = current_total_energy
                
                co2_raw = getattr(device, "room_co2_level", None)
                co2_val = f"{co2_raw}" if co2_raw is not None and co2_raw != 0 else "N/A"
                
                writer.writerow([
                    current_time, device.name, status, 
                    temp_amb, temp_tar, mode, fan, 
                    hourly_delta, co2_val
                ])
                print(f"[Background Logger] Logged {device.name} | Delta: {hourly_delta} kWh")
                
            except Exception as e:
                print(f"[Background Logger] Error logging device {device.name}: {e}")

async def background_logger_task(app: FastAPI):
    print("[Task] Hourly logging daemon is active.")
    try:
        while True:
            await run_unified_logging(app)
            await asyncio.sleep(POLLING_INTERVAL)
    except asyncio.CancelledError:
        print("[Task] Logging service stopped.")
