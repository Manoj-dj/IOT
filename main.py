from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import random, math, time
from datetime import datetime, timedelta
from collections import deque
from pydantic import BaseModel
from typing import Optional, List

app = FastAPI(title="Smart-Manhole Dashboard API")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

logs = deque(maxlen=200)
alert_history = deque(maxlen=100)
sim_logs = deque(maxlen=200)       # Simulator-generated logs
sim_alerts = deque(maxlen=100)     # Simulator-generated alerts
t_counter = [0.0]

THRESHOLDS = {
    "methane":     {"warning": 500,  "danger": 1000, "unit": "ppm",  "label": "Methane (CH₄)",     "max": 2000},
    "h2s":         {"warning": 5,    "danger": 10,   "unit": "ppm",  "label": "Hydrogen Sulfide",   "max": 50},
    "water_level": {"warning": 55,   "danger": 75,   "unit": "cm",   "label": "Water Level",        "max": 100},
    "temperature": {"warning": 40,   "danger": 50,   "unit": "°C",   "label": "Temperature",        "max": 70},
    "humidity":    {"warning": 78,   "danger": 90,   "unit": "%",    "label": "Humidity",           "max": 100},
    "ammonia":     {"warning": 100,  "danger": 200,  "unit": "ppm",  "label": "Ammonia (NH₃)",      "max": 400},
    "vibration":   {"warning": None, "danger": 1,    "unit": "flag", "label": "Vibration",          "max": 1},
}

MANHOLES = [
    {"id": "MH-001", "location": "Anna Nagar, Chennai",    "zone": "Zone A"},
    {"id": "MH-002", "location": "T. Nagar, Chennai",      "zone": "Zone B"},
    {"id": "MH-003", "location": "Adyar, Chennai",         "zone": "Zone C"},
    {"id": "MH-004", "location": "Tambaram, Chennai",      "zone": "Zone D"},
]

# ─── Live sensor data generation ────────────────────────────────────────────

def generate_data(manhole_id="MH-001"):
    t_counter[0] += 0.12
    t = t_counter[0]

    methane     = max(0,   min(2000, 220 + 120*abs(math.sin(t*0.3)) + random.gauss(0, 35)))
    h2s         = max(0,   min(50,   2.5 + 3.5*abs(math.sin(t*0.5)) + random.gauss(0, 0.6)))
    water_level = max(0,   min(100,  18  + 18*abs(math.sin(t*0.18)) + random.gauss(0, 2.5)))
    temperature = max(20,  min(70,   30  + 6*math.sin(t*0.1)        + random.gauss(0, 1.2)))
    humidity    = max(40,  min(100,  62  + 12*math.sin(t*0.15)      + random.gauss(0, 2)))
    ammonia     = max(0,   min(400,  55  + 55*abs(math.sin(t*0.38)) + random.gauss(0, 12)))
    vibration   = 1 if random.random() < 0.06 else 0

    if random.random() < 0.06: methane     += random.uniform(700, 1100)
    if random.random() < 0.04: h2s         += random.uniform(8, 20)
    if random.random() < 0.05: water_level += random.uniform(40, 60)
    if random.random() < 0.03: ammonia     += random.uniform(150, 250)

    methane     = round(max(0, min(2000, methane)), 1)
    h2s         = round(max(0, min(50,   h2s)), 2)
    water_level = round(max(0, min(100,  water_level)), 1)
    temperature = round(max(20, min(70,  temperature)), 1)
    humidity    = round(max(40, min(100, humidity)), 1)
    ammonia     = round(max(0, min(400,  ammonia)), 1)

    values = {
        "methane": methane, "h2s": h2s, "water_level": water_level,
        "temperature": temperature, "humidity": humidity, "ammonia": ammonia,
        "vibration": vibration
    }

    alerts = []
    for key, val in values.items():
        thresh = THRESHOLDS[key]
        level = None
        if val >= thresh["danger"]:
            level = "DANGER"
        elif thresh["warning"] and val >= thresh["warning"]:
            level = "WARNING"
        if level:
            alerts.append({
                "sensor": key, "label": thresh["label"],
                "value": val, "unit": thresh["unit"],
                "level": level, "threshold": thresh["danger"] if level == "DANGER" else thresh["warning"],
                "time": datetime.now().strftime("%H:%M:%S")
            })

    overall = "DANGER" if any(a["level"] == "DANGER" for a in alerts) else ("WARNING" if alerts else "SAFE")

    entry = {
        **values,
        "alerts": alerts,
        "status": overall,
        "manhole_id": manhole_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "worker_entry": "PROHIBITED" if overall == "DANGER" else ("CAUTION" if overall == "WARNING" else "PERMITTED"),
        "source": "live"
    }

    logs.append(entry)
    for a in alerts:
        a["manhole_id"] = manhole_id
        alert_history.appendleft(a)

    return entry

# ─── Simulator Models & Logic ────────────────────────────────────────────────

class SensorConfig(BaseModel):
    value: float
    threshold_warning: Optional[float] = None
    threshold_danger: Optional[float] = None
    noise_level: Optional[float] = 0.05   # fraction of value range

class SimulateRequest(BaseModel):
    manhole_id: Optional[str] = "SIM-001"
    num_logs: Optional[int] = 20
    interval_seconds: Optional[int] = 5   # simulated time step
    methane: Optional[SensorConfig] = None
    h2s: Optional[SensorConfig] = None
    water_level: Optional[SensorConfig] = None
    temperature: Optional[SensorConfig] = None
    humidity: Optional[SensorConfig] = None
    ammonia: Optional[SensorConfig] = None
    vibration: Optional[SensorConfig] = None

def _clamp(val, lo, hi):
    return max(lo, min(hi, val))

def _generate_sim_value(cfg: Optional[SensorConfig], sensor_key: str, noise_pct: float = 0.08) -> float:
    """Generate a realistic noisy value around the user-set value."""
    thresh = THRESHOLDS[sensor_key]
    max_val = thresh["max"]

    if cfg is None:
        # Use safe default (below warning)
        if thresh["warning"]:
            base = thresh["warning"] * 0.4
        else:
            base = 0.0
    else:
        base = cfg.value
        noise_pct = cfg.noise_level if cfg.noise_level is not None else noise_pct

    noise_range = max_val * noise_pct
    value = base + random.gauss(0, noise_range * 0.5)

    # Clamp to sensor's physical range
    if sensor_key == "temperature":
        return round(_clamp(value, 20, max_val), 1)
    elif sensor_key == "humidity":
        return round(_clamp(value, 40, max_val), 1)
    else:
        return round(_clamp(value, 0, max_val), 2 if sensor_key == "h2s" else 1)

def _classify(sensor_key: str, value: float, config: Optional[SensorConfig]) -> str:
    thresh = THRESHOLDS[sensor_key]
    # Use user-overridden thresholds if provided, else defaults
    warn = thresh["warning"]
    danger = thresh["danger"]
    if config:
        if config.threshold_warning is not None:
            warn = config.threshold_warning
        if config.threshold_danger is not None:
            danger = config.threshold_danger

    if value >= danger:
        return "DANGER"
    if warn is not None and value >= warn:
        return "WARNING"
    return "SAFE"

def generate_sim_logs(req: SimulateRequest) -> List[dict]:
    """Generate a batch of synthetic logs based on user-defined sensor config."""
    results = []
    now = datetime.now()

    sensor_keys = ["methane", "h2s", "water_level", "temperature", "humidity", "ammonia", "vibration"]
    configs = {
        "methane":     req.methane,
        "h2s":         req.h2s,
        "water_level": req.water_level,
        "temperature": req.temperature,
        "humidity":    req.humidity,
        "ammonia":     req.ammonia,
        "vibration":   req.vibration,
    }

    for i in range(req.num_logs):
        ts = now - timedelta(seconds=(req.num_logs - i) * req.interval_seconds)
        values = {}

        for key in sensor_keys:
            cfg = configs[key]
            if key == "vibration":
                # vibration: if user set value >= 1, simulate frequent detection
                if cfg and cfg.value >= 1:
                    values[key] = 1 if random.random() < 0.7 else 0
                else:
                    values[key] = 1 if random.random() < 0.05 else 0
            else:
                values[key] = _generate_sim_value(cfg, key)

        alerts = []
        for key in sensor_keys:
            val = values[key]
            thresh = THRESHOLDS[key]
            cfg = configs[key]
            level_str = _classify(key, val, cfg)

            if level_str in ("DANGER", "WARNING"):
                warn_thresh = thresh["warning"]
                danger_thresh = thresh["danger"]
                if cfg:
                    if cfg.threshold_warning is not None: warn_thresh = cfg.threshold_warning
                    if cfg.threshold_danger is not None:  danger_thresh = cfg.threshold_danger

                alerts.append({
                    "sensor": key,
                    "label": thresh["label"],
                    "value": val,
                    "unit": thresh["unit"],
                    "level": level_str,
                    "threshold": danger_thresh if level_str == "DANGER" else warn_thresh,
                    "time": ts.strftime("%H:%M:%S"),
                    "manhole_id": req.manhole_id,
                    "timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
                })

        overall = "DANGER" if any(a["level"] == "DANGER" for a in alerts) else ("WARNING" if alerts else "SAFE")

        entry = {
            **values,
            "alerts":       alerts,
            "status":       overall,
            "manhole_id":   req.manhole_id,
            "timestamp":    ts.strftime("%Y-%m-%d %H:%M:%S"),
            "worker_entry": "PROHIBITED" if overall == "DANGER" else ("CAUTION" if overall == "WARNING" else "PERMITTED"),
            "source":       "simulator",
        }
        results.append(entry)

        # Also append to sim stores
        sim_logs.append(entry)
        for a in alerts:
            sim_alerts.appendleft(a)

    return results


# ─── API Routes ──────────────────────────────────────────────────────────────

@app.get("/api/sensors")
def current_reading(manhole_id: str = "MH-001"):
    return generate_data(manhole_id)

@app.get("/api/logs")
def get_logs(n: int = 30):
    return list(logs)[-n:]

@app.get("/api/alerts")
def get_alerts(n: int = 20):
    return list(alert_history)[:n]

@app.get("/api/manholes")
def get_manholes():
    return MANHOLES

@app.get("/api/thresholds")
def get_thresholds():
    return THRESHOLDS

# ── Simulator endpoints ──

@app.post("/api/simulate")
def run_simulation(req: SimulateRequest):
    """Accept sensor config from frontend, generate synthetic logs, return them."""
    if req.num_logs < 1:
        req.num_logs = 1
    if req.num_logs > 100:
        req.num_logs = 100
    generated = generate_sim_logs(req)
    return {
        "logs": generated,
        "total": len(generated),
        "manhole_id": req.manhole_id,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

@app.get("/api/sim/logs")
def get_sim_logs(n: int = 50):
    return list(sim_logs)[-n:]

@app.get("/api/sim/alerts")
def get_sim_alerts(n: int = 50):
    return list(sim_alerts)[:n]

@app.delete("/api/sim/clear")
def clear_sim_logs():
    sim_logs.clear()
    sim_alerts.clear()
    return {"status": "cleared"}

@app.get("/")
def serve():
    return FileResponse("dashboard.html")