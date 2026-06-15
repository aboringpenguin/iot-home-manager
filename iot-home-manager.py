import uvicorn
from iot_home_manager.config import SERVER_PORT

if __name__ == "__main__":
    uvicorn.run("iot_home_manager.app:app", host="0.0.0.0", port=SERVER_PORT, log_level="info")