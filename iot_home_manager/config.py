import os
from dotenv import load_dotenv

# ==================== CONFIGURATION ====================
load_dotenv()

def get_secret(env_name: str) -> str:
    # First check default Docker Secrets directory
    docker_secret_path = f"/run/secrets/{env_name.lower()}"
    if os.path.exists(docker_secret_path):
        try:
            with open(docker_secret_path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except IOError as e:
            print(f"[Warning] Failed to read secret file at {docker_secret_path}: {e}")
    # Fallback to standard environment variables
    return os.getenv(env_name, "")

EMAIL = get_secret("MELCLOUD_EMAIL")
PASSWORD = get_secret("MELCLOUD_PASSWORD")
POLLING_INTERVAL = int(os.getenv("LOG_INTERVAL", 3600))
SERVER_PORT = int(os.getenv("SERVER_PORT", 8000))
# ========================================================
