"""Smoke test for React-era backend routes."""
from pathlib import Path
import json

from fastapi.testclient import TestClient

from backend.main import app

client = TestClient(app)
r = client.get("/health")
print("health", r.status_code, r.json())
r = client.get("/")
print("root", r.status_code, "len", len(r.text), "has_app", "root" in r.text or "微生物" in r.text)

img = Path("test1.jpg")
assert img.exists(), "test1.jpg missing"
files = [("images", (img.name, img.read_bytes(), "image/jpeg"))]
r = client.post("/api/v1/batch/refs", files=files)
print("refs", r.status_code)
assert r.status_code == 200, r.text
ref = r.json()["refs"][0]
rid = ref["id"]
print("ref meta", ref["width"], ref["height"], "thumb_len", len(ref["thumb_base64"]))

r = client.put(
    f"/api/v1/batch/refs/{rid}",
    json={"total_gt": 95, "points": [{"x": 10, "y": 20}]},
)
print("put ref", r.status_code, r.json() if r.status_code == 200 else r.text)
assert r.status_code == 200, r.text
assert r.json()["total_gt"] == 95
assert r.json()["points"][0]["x"] == 10

r = client.post(
    "/api/v1/batch/calibrate",
    json={
        "refs": [{"id": rid, "total_gt": 95, "points": []}],
        "max_evals": 5,
        "time_limit_sec": 25,
    },
)
print("calibrate", r.status_code)
assert r.status_code == 200, r.text
data = r.json()
print("success", data.get("success"), "fit", data.get("fit_error"), "msg", data.get("message"))
plates = data.get("plate_results") or []
if plates:
    print("plate keys sample", sorted(plates[0].keys()))
    assert "predicted_count" in plates[0] or "name" in plates[0]
params = data.get("params") or {"blur_ksize": 7}

files = [("images", ("test2.jpg", Path("test2.jpg").read_bytes(), "image/jpeg"))]
r2 = client.post("/api/v1/batch/run", data={"params": json.dumps(params)}, files=files)
print("run", r2.status_code)
assert r2.status_code == 200, r2.text
item = r2.json()["items"][0]
print("run item", item["name"], item["count"], "err", item.get("error"))

files = [("image", ("test1.jpg", img.read_bytes(), "image/jpeg"))]
r = client.post("/api/v1/count_smart", files=files)
print("smart", r.status_code, r.json().get("count") if r.status_code == 200 else r.text[:300])
print("OK")
