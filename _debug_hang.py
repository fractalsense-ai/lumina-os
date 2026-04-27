"""Debug script to locate the exact hang point in POST /api/chat."""
import sys, os, threading, time

def watchdog():
    time.sleep(10)
    print("\n*** WATCHDOG: 10s expired, dumping all threads ***", flush=True)
    import traceback
    for tid, frame in sys._current_frames().items():
        print(f"\n--- Thread {tid} ---", flush=True)
        traceback.print_stack(frame)
    os._exit(1)

threading.Thread(target=watchdog, daemon=True).start()

os.environ["LUMINA_RUNTIME_CONFIG_PATH"] = "model-packs/education/cfg/runtime-config.yaml"
os.environ.pop("LUMINA_DOMAIN_REGISTRY_PATH", None)

import lumina.api.server as srv
from lumina.persistence.adapter import NullPersistenceAdapter
from lumina.core.yaml_loader import load_yaml
from lumina.auth import auth

srv.PERSISTENCE = NullPersistenceAdapter()
srv.BOOTSTRAP_MODE = True
srv._session_containers.clear()
auth.JWT_SECRET = "test-secret"
srv.PERSISTENCE.load_subject_profile = load_yaml

from starlette.testclient import TestClient
client = TestClient(srv.app)

print("Registering user...", flush=True)
resp = client.post("/api/auth/register", json={"username": "admin", "password": "test-pass-123", "role": "user"})
print(f"Register: {resp.status_code}", flush=True)
token = resp.json()["access_token"]

print("Sending chat...", flush=True)
resp = client.post(
    "/api/chat",
    json={"message": "hello", "deterministic_response": True},
    headers={"Authorization": f"Bearer {token}"},
)
print(f"Chat: {resp.status_code}", flush=True)
print("Done!", flush=True)
