import asyncio
import csv
import os
from datetime import datetime, timedelta
from typing import Optional
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse
import aiohttp
import pymelcloud
from dotenv import load_dotenv

# ==================== CONFIGURATION ====================
load_dotenv()

EMAIL = os.getenv("MELCLOUD_EMAIL")
PASSWORD = os.getenv("MELCLOUD_PASSWORD")
POLLING_INTERVAL = int(os.getenv("LOG_INTERVAL", 3600))
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
# ========================================================

async def lifespan(app: FastAPI):
    # --- STARTUP PHASE ---
    app.state.http_session = aiohttp.ClientSession()
    app.state.energy_history = {}
    app.state.active_timers = {}
    
    print("[System] Synchronizing with MELCloud platform...")
    try:
        token = await pymelcloud.login(EMAIL, PASSWORD, session=app.state.http_session)
        devices_dict = await pymelcloud.get_devices(token, session=app.state.http_session)
        app.state.mitsubishi_devices = devices_dict.get("ata", [])
        
        for device in app.state.mitsubishi_devices:
            await device.update()
            app.state.energy_history[device.name] = getattr(device, "total_energy_consumed", 0.0)
            
        print(f"[System] Daemon ready. Synchronized {len(app.state.mitsubishi_devices)} split units.")
    except Exception as e:
        print(f"[CRITICAL] Boot failure: {e}")
        raise e

    logger_task = asyncio.create_task(background_logger_task(app))
    
    yield  # --- SERVER RUNNING CONTEXT ---
    
    # --- SHUTDOWN PHASE ---
    print("\n[System] Stopping daemon...")
    logger_task.cancel()
    
    for timer_task in app.state.active_timers.values():
        timer_task.cancel()
        
    await asyncio.gather(logger_task, *app.state.active_timers.values(), return_exceptions=True)
    await app.state.http_session.close()
    print("[System] Clean exit achieved.")


app = FastAPI(lifespan=lifespan, title="Iot Home Manager")


# ==================== CORE LOGGING LOGIC ====================

def get_daily_filename():
    current_date = datetime.now().strftime("%Y-%m-%d")
    return f"log_{current_date}.csv"

def initialize_csv(filename):
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

async def timer_worker(device, action, payload, delay_seconds, app: FastAPI):
    timer_key = f"{device.name}_{action}"
    try:
        await asyncio.sleep(delay_seconds)
        
        await device.update()
        current_power = device.power
        
        if action == "off":
            if not current_power:
                print(f"[Timer] Aborted: {device.name} is already OFF. No command sent.")
                return
            await device.set({"power": False})
        elif action == "on":
            if current_power:
                print(f"[Timer] Aborted: {device.name} is already ON. No command sent.")
                return
            await device.set(payload)
            
        print(f"[Timer] Auto-{action.upper()} executed successfully for {device.name}")
    except asyncio.CancelledError:
        print(f"[Timer] Auto-{action.upper()} task canceled for {device.name}")
    finally:
        app.state.active_timers.pop(timer_key, None)


# ==================== FASTAPI ENDPOINTS ====================

@app.get("/help", response_class=PlainTextResponse)
@app.get("/", response_class=PlainTextResponse)
async def get_api_help():
    """Returns a dynamic, readable command blueprint helper directly in the terminal."""
    return """
================================================================================
                    IOT HOME MANAGER API - COMMAND BLUEPRINT HELPER                    
================================================================================
Base URL: http://127.0.0.1:8000

[1] SYSTEM DIAGNOSTICS (GET)
    --> Check real-time hardware status, vane angles, and active timers.
    PowerShell: Invoke-RestMethod -Method Get -Uri "http://127.0.0.1:8000/status"
    Curl/Bash:  curl.exe -X GET "http://127.0.0.1:8000/status"

[2] IMMEDIATE CONTROL & EDIT (POST)
    --> Turn a unit ON, OFF or use SET to tweak values at runtime.
    --> Redundant operations are automatically filtered out.
    
    PowerShell (Simple ON):
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/control/1/on"
    PowerShell (Runtime parameter change - SET):
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/control/1/set?temp=22&vane_h=swing&vane_v=auto"
    PowerShell (OFF):
        Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/control/1/off"

[3] COMBINED TRANSIENT RUN (POST)
    --> Turns a unit ON immediately and schedules an automatic shutdown in a single call.
    --> Requires '?until=HH:MM'. Supports optional parameters (temp, mode, fan, vane_h, vane_v).
    PowerShell: Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/control/1/on-until?until=03:00&temp=24&mode=dry"

[4] ONE-TIME SHUTDOWN TIMER (POST)
    --> Schedules a future shutdown. Requires '?until=HH:MM'.
    PowerShell: Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/control/1/timer/off?until=02:30"

[5] ONE-TIME STARTUP TIMER (POST)
    --> Schedules a future startup with predefined states and vane positions. Requires '?at=HH:MM'.
    PowerShell: Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8000/control/1/timer/on?at=07:30&temp=24&vane_h=1"

================================================================================
            HARDWARE PARAMETER SPECIFICATIONS (FOR ON, SET & TIMERS)           
================================================================================
Append these optional parameters as query strings (?param=value&param2=value)

    • temp=value (Type: float) -> Target temperature setting (16.0 to 31.0).
    • mode=value (Type: string) -> Profiles: cool, heat, dry, fan.
    • fan=value (Type: integer or string) -> Speeds: auto, 1, 2, 3, 4.
    
    • vane_h=value (Type: integer or string) -> Horizontal vane position (Alto/Basso):
      [ auto, swing, 1, 2, 3, 4 ]
    • vane_v=value (Type: integer or string) -> Vertical vane position (Sinistra/Destra):
      [ auto, swing, 1, 2, 3, 4, 5 ]

    • days=value (Type: integer) - *Timer Endpoints Only*
      Offset count to schedule actions beyond today (e.g. &days=13).

💡 INTERACTIVE SWAGGER DASHBOARD:
    Open your web browser and navigate to: http://127.0.0.1:8000/docs
================================================================================
"""


@app.get("/status", response_class=PlainTextResponse)
async def get_status(request: Request):
    """Returns real-time enhanced diagnostics of all connected devices."""
    air_conditioners = request.app.state.mitsubishi_devices
    response_text = "=========================== MITSUBISHI SYSTEM STATUS ===========================\n"
    
    for idx, device in enumerate(air_conditioners):
        try:
            await device.update()
            status = "🟢 ON" if device.power else "🔴 OFF"
            active_on = "Active" if f"{device.name}_on" in request.app.state.active_timers else "None"
            active_off = "Active" if f"{device.name}_off" in request.app.state.active_timers else "None"
            
            mode = device.operation_mode if device.operation_mode else "N/A"
            fan = device.fan_speed if device.fan_speed else "N/A"
            v_vane = getattr(device, "vane_vertical", "N/A")
            h_vane = getattr(device, "vane_horizontal", "N/A")
            
            response_text += (
                f"[{idx}] {device.name:<18} -> Status: {status:<6} | "
                f"Ambient: {device.room_temperature}°C | Target: {device.target_temperature}°C\n"
                f"    [Settings] Mode: {str(mode).upper():<6} | Fan: {str(fan).upper():<5} | "
                f"Vane-V: {str(v_vane).upper():<8} | Vane-H: {str(h_vane).upper()}\n"
                f"    [System]   Odometer: {device.total_energy_consumed} kWh | Timer_ON: {active_on:<6} | Timer_OFF: {active_off}\n"
                f"--------------------------------------------------------------------------------\n"
            )
        except Exception as e:
            response_text += f"[{idx}] {device.name:<18} -> Error parsing data: {e}\n--------------------------------------------------------------------------------\n"
            
    return response_text


# ==================== CRITICAL: ROUTING ORDER IS PRECUIOUS ====================

# 1. SPECIFIC PERMANENT PATHS FIRST (Prevents {action} string collision)

@app.post("/control/{idx}/on-until", response_class=PlainTextResponse)
async def turn_on_until(
    idx: int,
    until: str,
    request: Request,
    days: int = 0,
    temp: Optional[float] = None,
    mode: Optional[str] = None,
    fan: Optional[str] = None,
    vane_h: Optional[str] = None,
    vane_v: Optional[str] = None
):
    """Turns a device ON immediately with optional settings, and schedules an automatic OFF timer."""
    air_conditioners = request.app.state.mitsubishi_devices
    
    if idx < 0 or idx >= len(air_conditioners):
        raise HTTPException(status_code=404, detail="Error: Index out of range.\n")
        
    device = air_conditioners[idx]
    
    try:
        now = datetime.now()
        target_time = datetime.strptime(until, "%H:%M").time()
        target_date = now.date() + timedelta(days=days)
        target_datetime = datetime.combine(target_date, target_time)
        
        if target_datetime <= now:
            raise HTTPException(status_code=400, detail=f"❌ Error: Shutdown time {target_datetime.strftime('%Y-%m-%d %H:%M')} has already passed.\n")
            
        delay_seconds = int((target_datetime - now).total_seconds())
    except ValueError:
        raise HTTPException(status_code=400, detail="Error: Invalid time format for 'until'. Use HH:MM.\n")

    # Build Immediate Execution Payload
    payload = {"power": True}
    if mode: payload["operation_mode"] = mode
    if temp: payload["target_temperature"] = temp
    if fan:  payload["fan_speed"] = int(fan) if fan.isdigit() else fan
    if vane_h: payload["vane_horizontal"] = vane_h
    if vane_v: payload["vane_vertical"] = vane_v
        
    try:
        print(f"[API] On-Until execution. Turning ON {device.name} immediately: {payload}")
        await device.set(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"❌ MELCloud Execution Error: {e}\n")

    # Arm Background Countdown
    timer_key = f"{device.name}_off"
    if timer_key in request.app.state.active_timers:
        request.app.state.active_timers[timer_key].cancel()

    task = asyncio.create_task(timer_worker(device, "off", {}, delay_seconds, request.app))
    request.app.state.active_timers[timer_key] = task
    
    print(f"[API] On-Until success. {device.name} is ON. Auto-OFF armed for {target_datetime.strftime('%Y-%m-%d %H:%M')}.")
    return (
        f"✅ {device.name} turned ON successfully with requested parameters.\n"
        f"⏰ Auto-OFF timer armed: will turn OFF on {target_date.strftime('%Y-%m-%d')} at {until} (in {delay_seconds} seconds).\n"
    )


# 2. STANDARD TIMERS ROUTE

@app.post("/control/{idx}/timer/{action}", response_class=PlainTextResponse)
async def set_timer(
    idx: int, 
    action: str, 
    request: Request,
    at: Optional[str] = None, 
    until: Optional[str] = None, 
    days: int = 0,
    temp: Optional[float] = None, 
    mode: Optional[str] = None, 
    fan: Optional[str] = None,
    vane_h: Optional[str] = None,
    vane_v: Optional[str] = None
):
    """Schedules a future concurrent action (ON/OFF) using either ?at=HH:MM or ?until=HH:MM."""
    air_conditioners = request.app.state.mitsubishi_devices
    action = action.lower()
    target_time_str = at or until
    
    if action not in ["on", "off"]:
        raise HTTPException(status_code=400, detail="Error: Invalid timer action. Use 'on' or 'off'.\n")
        
    if not target_time_str:
        raise HTTPException(status_code=400, detail="Error: Missing time parameter (?at=HH:MM or ?until=HH:MM).\n")
        
    if idx < 0 or idx >= len(air_conditioners):
        raise HTTPException(status_code=404, detail="Error: Index out of range.\n")
        
    device = air_conditioners[idx]
    payload = {}
    
    if action == "on":
        payload["power"] = True
        if mode: payload["operation_mode"] = mode
        if temp: payload["target_temperature"] = temp
        if fan:  payload["fan_speed"] = int(fan) if fan.isdigit() else fan
        if vane_h: payload["vane_horizontal"] = vane_h
        if vane_v: payload["vane_vertical"] = vane_v
            
    try:
        now = datetime.now()
        target_time = datetime.strptime(target_time_str, "%H:%M").time()
        target_date = now.date() + timedelta(days=days)
        target_datetime = datetime.combine(target_date, target_time)
        
        if target_datetime <= now:
            raise HTTPException(status_code=400, detail=f"❌ Error: Scheduled time {target_datetime.strftime('%Y-%m-%d %H:%M')} has already passed.\n")
            
        delay_seconds = int((target_datetime - now).total_seconds())
    except ValueError:
        raise HTTPException(status_code=400, detail="Error: Invalid time format. Use HH:MM.\n")

    timer_key = f"{device.name}_{action}"
    if timer_key in request.app.state.active_timers:
        request.app.state.active_timers[timer_key].cancel()

    task = asyncio.create_task(timer_worker(device, action, payload, delay_seconds, request.app))
    request.app.state.active_timers[timer_key] = task
    
    print(f"[API] Timer armed for {device.name}. {action.upper()} scheduled at {target_datetime.strftime('%Y-%m-%d %H:%M')} (in {delay_seconds} seconds).")
    return f"⏰ Timer set! {device.name} will turn {action.upper()} on {target_date.strftime('%Y-%m-%d')} at {target_time_str}.\n"


# 3. GENERIC DIRECT CONTROL ROUTE (Must sit at the bottom)

@app.post("/control/{idx}/{action}", response_class=PlainTextResponse)
async def control_device(
    idx: int, 
    action: str, 
    request: Request,
    temp: Optional[float] = None, 
    mode: Optional[str] = None, 
    fan: Optional[str] = None,
    vane_h: Optional[str] = None,
    vane_v: Optional[str] = None
):
    """Handles real-time hardware execution (ON/OFF/SET) via query parameters with redundancy filtering."""
    air_conditioners = request.app.state.mitsubishi_devices
    action = action.lower()
    
    if idx < 0 or idx >= len(air_conditioners):
        raise HTTPException(status_code=404, detail="Error: Index out of range.\n")
        
    if action not in ["on", "off", "set"]:
        raise HTTPException(status_code=400, detail="Error: Invalid action. Use 'on', 'off', or 'set'.\n")
        
    device = air_conditioners[idx]
    
    await device.update()
    current_power = device.power
    
    if action == "off" and not current_power:
        return f"ℹ️ Command skipped: {device.name} is already OFF.\n"
        
    if action == "on" and current_power:
        if not temp and not mode and not fan and not vane_h and not vane_v:
            return f"ℹ️ Command skipped: {device.name} is already ON with no parameter updates. Use 'set' to change values.\n"
            
    if action == "set":
        if not current_power:
            return f"❌ Command rejected: Cannot modify parameters because {device.name} is currently OFF. Turn it ON first.\n"
        if not temp and not mode and not fan and not vane_h and not vane_v:
            return f"ℹ️ Command skipped: 'set' action called but no parameters were provided.\n"

    payload = {}
    if action in ["on", "set"]:
        payload["power"] = True
        if mode: payload["operation_mode"] = mode
        if temp: payload["target_temperature"] = temp
        if fan:  payload["fan_speed"] = int(fan) if fan.isdigit() else fan
        if vane_h: payload["vane_horizontal"] = vane_h
        if vane_v: payload["vane_vertical"] = vane_v
    elif action == "off":
        payload["power"] = False
        
    try:
        print(f"[API] Direct control command [{action.upper()}] for {device.name}: {payload}")
        await device.set(payload)
        return f"✅ Command executed for {device.name}: {payload}\n"
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"❌ MELCloud error: {e}\n")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("iot-home-manager:app", host="0.0.0.0", port=SERVER_PORT, log_level="info")