import asyncio
from fastapi import FastAPI

async def timer_worker(device, action: str, payload: dict, delay_seconds: int, app: FastAPI):
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
