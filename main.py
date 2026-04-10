from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import random, math, time, sqlite3, smtplib, threading, os, json
from datetime import datetime, timedelta
from collections import deque
from pydantic import BaseModel
from typing import Optional, List
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

app = FastAPI(title="Smart-Manhole Dashboard API")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

logs = deque(maxlen=200)
alert_history = deque(maxlen=100)
sim_logs = deque(maxlen=200)       # Simulator-generated logs
sim_alerts = deque(maxlen=100)     # Simulator-generated alerts
t_counter = [0.0]

# ─── Notification / Subscriber Database ──────────────────────────────────────
DB_PATH = "notifications.db"

def init_db():
    """Create subscriber table and config table if they don't exist."""
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS subscribers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL DEFAULT 'User',
            email TEXT,
            phone TEXT,
            notify_warning INTEGER DEFAULT 1,
            notify_danger  INTEGER DEFAULT 1,
            registered_at  TEXT DEFAULT (datetime('now','localtime')),
            enabled        INTEGER DEFAULT 1
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS smtp_config (
            id          INTEGER PRIMARY KEY CHECK (id = 1),
            host        TEXT DEFAULT 'smtp.gmail.com',
            port        INTEGER DEFAULT 587,
            username    TEXT DEFAULT '',
            password    TEXT DEFAULT '',
            from_name   TEXT DEFAULT 'Smart-Manhole Alerts'
        )
    """)
    # Insert default smtp config row if missing
    cur.execute("INSERT OR IGNORE INTO smtp_config (id) VALUES (1)")
    # Notification log table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS notification_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            sent_at     TEXT DEFAULT (datetime('now','localtime')),
            recipient   TEXT,
            channel     TEXT,
            level       TEXT,
            manhole_id  TEXT,
            sensors     TEXT,
            status      TEXT
        )
    """)
    con.commit()
    con.close()

init_db()

# Track last-sent alert to avoid spam — stores set of (manhole_id, sensor, level) tuples
_last_sent_alerts: set = set()
_notif_lock = threading.Lock()


def _get_smtp_config() -> dict:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT * FROM smtp_config WHERE id=1").fetchone()
    con.close()
    if row:
        return dict(row)
    return {}


def _send_email(cfg: dict, to_addr: str, subject: str, html_body: str, text_body: str) -> bool:
    """Send an HTML email via SMTP. Returns True on success."""
    try:
        if not cfg.get("username") or not cfg.get("password"):
            return False  # Not configured
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = f"{cfg.get('from_name', 'Smart-Manhole')} <{cfg['username']}>"
        msg["To"]      = to_addr
        msg.attach(MIMEText(text_body, "plain"))
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP(cfg.get("host", "smtp.gmail.com"), int(cfg.get("port", 587))) as server:
            server.ehlo()
            server.starttls()
            server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["username"], to_addr, msg.as_string())
        return True
    except Exception as e:
        print(f"[SMTP ERROR] {e}")
        return False


def _build_alert_email(alerts: list, manhole_id: str, status: str) -> tuple:
    """Build (subject, html, text) for an alert notification."""
    level_emoji = "🔴" if status == "DANGER" else "🟡"
    subject = f"{level_emoji} [{status}] Smart-Manhole {manhole_id} — Sensor Alert"

    rows_html = "".join([
        f"""
        <tr>
          <td style='padding:8px 12px;border-bottom:1px solid #30363d;color:#e6edf3;'>{a['label']}</td>
          <td style='padding:8px 12px;border-bottom:1px solid #30363d;font-weight:700;
              color:{"#f85149" if a["level"]=="DANGER" else "#d29922"};'>{a['level']}</td>
          <td style='padding:8px 12px;border-bottom:1px solid #30363d;color:#e6edf3;'>{a['value']} {a['unit']}</td>
          <td style='padding:8px 12px;border-bottom:1px solid #30363d;color:#8b949e;'>&gt; {a['threshold']} {a['unit']}</td>
        </tr>"""
        for a in alerts
    ])

    html = f"""
    <html><body style='background:#0d1117;color:#e6edf3;font-family:Inter,Arial,sans-serif;margin:0;padding:0;'>
    <div style='max-width:600px;margin:0 auto;padding:24px;'>
      <div style='background:linear-gradient(135deg,#1f6feb,#388bfd);padding:20px 24px;border-radius:12px 12px 0 0;'>
        <div style='font-size:22px;font-weight:800;color:#fff;'>🚨 Smart-Manhole Alert</div>
        <div style='font-size:13px;color:rgba(255,255,255,0.8);margin-top:4px;'>Real-time IoT Safety Notification</div>
      </div>
      <div style='background:#161b22;border:1px solid #30363d;border-top:none;border-radius:0 0 12px 12px;padding:24px;'>
        <div style='background:{"#3d1a1a" if status=="DANGER" else "#2d2500"};border:1px solid {"#f85149" if status=="DANGER" else "#d29922"};border-radius:8px;padding:14px;margin-bottom:20px;'>
          <div style='font-size:16px;font-weight:700;color:{"#f85149" if status=="DANGER" else "#d29922"};'>{level_emoji} Status: {status}</div>
          <div style='font-size:13px;color:#8b949e;margin-top:4px;'>Manhole: <b style='color:#58a6ff;'>{manhole_id}</b> · Time: {datetime.now().strftime("%d %b %Y, %H:%M:%S")}</div>
        </div>
        <div style='font-size:13px;font-weight:600;color:#8b949e;text-transform:uppercase;letter-spacing:1px;margin-bottom:10px;'>Triggered Sensors</div>
        <table width='100%' style='border-collapse:collapse;background:#0d1117;border-radius:8px;overflow:hidden;border:1px solid #30363d;'>
          <thead><tr style='background:#21262d;'>
            <th style='padding:10px 12px;text-align:left;font-size:11px;color:#8b949e;'>Sensor</th>
            <th style='padding:10px 12px;text-align:left;font-size:11px;color:#8b949e;'>Level</th>
            <th style='padding:10px 12px;text-align:left;font-size:11px;color:#8b949e;'>Value</th>
            <th style='padding:10px 12px;text-align:left;font-size:11px;color:#8b949e;'>Threshold</th>
          </tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        <div style='margin-top:20px;padding:14px;background:#0d2318;border:1px solid rgba(63,185,80,0.3);border-radius:8px;font-size:12px;color:#8b949e;'>
          ⚡ <b style='color:#3fb950;'>Action Required:</b> {"Do NOT allow worker entry. Evacuate and contact supervisor immediately." if status == "DANGER" else "Monitor closely. Use PPE if entry is required."}
        </div>
        <div style='margin-top:24px;text-align:center;font-size:11px;color:#555;'>Smart-Manhole+ · Municipal IoT Safety System · Chennai Smart City</div>
      </div>
    </div></body></html>
    """

    text_lines = [f"SMART-MANHOLE ALERT [{status}]", f"Manhole: {manhole_id}", f"Time: {datetime.now().strftime('%d %b %Y, %H:%M:%S')}", ""]
    for a in alerts:
        text_lines.append(f"  {a['label']}: {a['value']} {a['unit']} [{a['level']}] > {a['threshold']}")
    text_lines += ["", "This is an automated alert from the Smart-Manhole IoT system."]
    return subject, html, "\n".join(text_lines)


def _dispatch_notifications(entry: dict):
    """Called after every sensor reading that has alerts. Dispatches emails to subscribers."""
    global _last_sent_alerts
    alerts = entry.get("alerts", [])
    if not alerts:
        return

    manhole_id = entry.get("manhole_id", "MH-001")
    status     = entry.get("status", "SAFE")

    # Build a fingerprint for this alert batch to prevent duplicate sends
    fingerprint = frozenset((manhole_id, a["sensor"], a["level"]) for a in alerts)
    with _notif_lock:
        if fingerprint == _last_sent_alerts:
            return  # Same alert already sent
        _last_sent_alerts = fingerprint

    cfg = _get_smtp_config()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    subs = con.execute(
        "SELECT * FROM subscribers WHERE enabled=1"
    ).fetchall()
    con.close()

    if not subs:
        return

    subject, html_body, text_body = _build_alert_email(alerts, manhole_id, status)

    for sub in subs:
        sub = dict(sub)
        # Filter by subscriber preferences
        if status == "WARNING" and not sub.get("notify_warning"):
            continue
        if status == "DANGER" and not sub.get("notify_danger"):
            continue

        # Email notification
        email = sub.get("email")
        if email:
            ok = _send_email(cfg, email, subject, html_body, text_body)
            _log_notification(sub.get("email", ""), "email", status, manhole_id, alerts, "sent" if ok else "failed")


def _log_notification(recipient, channel, level, manhole_id, alerts, status):
    sensors_json = json.dumps([{"sensor": a["sensor"], "level": a["level"], "value": a["value"]} for a in alerts])
    try:
        con = sqlite3.connect(DB_PATH)
        con.execute(
            "INSERT INTO notification_log (recipient, channel, level, manhole_id, sensors, status) VALUES (?,?,?,?,?,?)",
            (recipient, channel, level, manhole_id, sensors_json, status)
        )
        con.commit()
        con.close()
    except Exception as e:
        print(f"[LOG ERROR] {e}")

# ─── Wokwi / ESP32 real sensor store ─────────────────────────────────────────
# Stores the latest reading posted from the ESP32 (via Wokwi or real hardware)
wokwi_latest: dict = {}   # empty = no real data yet, fall back to synthetic

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

# ─── Wokwi / ESP32 ingest model ─────────────────────────────────────────────
class WokwiPayload(BaseModel):
    """Payload sent by the ESP32 sketch via HTTP POST /api/wokwi."""
    gas: float                          # raw ADC value from MQ sensor
    temperature: float                  # DHT22 °C
    humidity: float                     # DHT22 %
    distance: float                     # HC-SR04 cm  (water level distance)
    buzzer: Optional[int] = 0           # 1 if buzzer is ON
    led: Optional[int] = 0              # 1 if LED is ON
    manhole_id: Optional[str] = "MH-001"


def _build_wokwi_entry(p: WokwiPayload) -> dict:
    """Convert raw ESP32 payload into the standard dashboard entry format."""
    # Map gas ADC (0-4095) → approximate methane ppm  (linear scale to 2000 ppm)
    methane = round(min(2000.0, (p.gas / 4095.0) * 2000.0), 1)

    # Water level: sensor returns distance-to-water-surface in cm.
    # Invert so higher water → higher 'water_level' metric (cap at 100 cm).
    # If distance == 0 or > 400, treat as "no reading" → keep 0
    if 0 < p.distance <= 400:
        water_level = round(min(100.0, max(0.0, 100.0 - p.distance)), 1)
    else:
        water_level = 0.0

    temperature = round(min(70.0, max(20.0, p.temperature)), 1)
    humidity    = round(min(100.0, max(40.0, p.humidity)), 1)

    # Synthetic fill-ins for sensors not on the Wokwi board
    h2s     = round(max(0.0, min(50.0,  2.5 + random.gauss(0, 0.4))), 2)
    ammonia = round(max(0.0, min(400.0, 55.0 + random.gauss(0, 10))), 1)
    vibration = 0

    values = {
        "methane": methane, "h2s": h2s, "water_level": water_level,
        "temperature": temperature, "humidity": humidity,
        "ammonia": ammonia, "vibration": vibration,
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
                "level": level,
                "threshold": thresh["danger"] if level == "DANGER" else thresh["warning"],
                "time": datetime.now().strftime("%H:%M:%S")
            })

    # Also honour the ESP32's own buzzer/LED alert flag
    if p.buzzer or p.led:
        already = {a["sensor"] for a in alerts}
        if "methane" not in already:
            alerts.append({
                "sensor": "esp32_alert", "label": "ESP32 Alert (Buzzer/LED)",
                "value": 1, "unit": "flag", "level": "WARNING",
                "threshold": 1, "time": datetime.now().strftime("%H:%M:%S")
            })

    overall = "DANGER" if any(a["level"] == "DANGER" for a in alerts) else ("WARNING" if alerts else "SAFE")

    entry = {
        **values,
        "alerts": alerts,
        "status": overall,
        "manhole_id": p.manhole_id,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "worker_entry": "PROHIBITED" if overall == "DANGER" else ("CAUTION" if overall == "WARNING" else "PERMITTED"),
        "source": "wokwi",
        # Keep raw esp32 fields for debugging
        "esp32_raw": {"gas_adc": p.gas, "distance_cm": p.distance, "buzzer": p.buzzer, "led": p.led},
    }
    return entry


@app.post("/api/wokwi")
def ingest_wokwi(payload: WokwiPayload):
    """Receive real sensor data from the ESP32 (Wokwi or physical board)."""
    global wokwi_latest
    entry = _build_wokwi_entry(payload)
    wokwi_latest = entry
    # Also push into the live log / alert history
    logs.append(entry)
    for a in entry["alerts"]:
        a["manhole_id"] = payload.manhole_id
        alert_history.appendleft(a)
    # Dispatch notifications in background thread
    if entry.get("alerts"):
        threading.Thread(target=_dispatch_notifications, args=(entry,), daemon=True).start()
    return {"status": "ok", "processed": entry}


@app.get("/api/wokwi/status")
def wokwi_status():
    """Check whether real ESP32 data is being received."""
    if wokwi_latest:
        return {"connected": True, "last_update": wokwi_latest.get("timestamp"), "latest": wokwi_latest}
    return {"connected": False, "message": "No data received yet from ESP32/Wokwi"}


@app.get("/api/sensors")
def current_reading(manhole_id: str = "MH-001"):
    # If we have real Wokwi data for MH-001, return it instead of synthetic
    if manhole_id == "MH-001" and wokwi_latest:
        entry = wokwi_latest
    else:
        entry = generate_data(manhole_id)
    # Dispatch notifications in background if alert present
    if entry.get("alerts"):
        threading.Thread(target=_dispatch_notifications, args=(dict(entry),), daemon=True).start()
    return entry

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


# ─── Notification Subscriber APIs ────────────────────────────────────────────

class SubscriberRegister(BaseModel):
    name: str
    email: Optional[str] = None
    phone: Optional[str] = None
    notify_warning: Optional[bool] = True
    notify_danger:  Optional[bool] = True

class SmtpConfigUpdate(BaseModel):
    host:      Optional[str] = "smtp.gmail.com"
    port:      Optional[int] = 587
    username:  Optional[str] = ""
    password:  Optional[str] = ""
    from_name: Optional[str] = "Smart-Manhole Alerts"

@app.post("/api/notifications/register")
def register_subscriber(sub: SubscriberRegister):
    """Register an email/phone for alert notifications."""
    if not sub.email and not sub.phone:
        raise HTTPException(status_code=400, detail="Provide at least an email or phone number.")
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Check for duplicate
    if sub.email:
        existing = cur.execute("SELECT id FROM subscribers WHERE email=? AND enabled=1", (sub.email,)).fetchone()
        if existing:
            con.close()
            raise HTTPException(status_code=409, detail="This email is already registered.")
    cur.execute(
        "INSERT INTO subscribers (name, email, phone, notify_warning, notify_danger) VALUES (?,?,?,?,?)",
        (sub.name, sub.email, sub.phone, int(sub.notify_warning), int(sub.notify_danger))
    )
    sub_id = cur.lastrowid
    con.commit()
    con.close()
    return {"status": "registered", "id": sub_id, "message": f"Alerts will be sent to {sub.email or sub.phone}"}

@app.get("/api/notifications/subscribers")
def list_subscribers():
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, name, email, phone, notify_warning, notify_danger, registered_at, enabled FROM subscribers ORDER BY id DESC").fetchall()
    con.close()
    return [{"id": r["id"], "name": r["name"], "email": r["email"], "phone": r["phone"],
             "notify_warning": bool(r["notify_warning"]), "notify_danger": bool(r["notify_danger"]),
             "registered_at": r["registered_at"], "enabled": bool(r["enabled"])} for r in rows]

@app.delete("/api/notifications/subscribers/{sub_id}")
def delete_subscriber(sub_id: int):
    con = sqlite3.connect(DB_PATH)
    con.execute("UPDATE subscribers SET enabled=0 WHERE id=?", (sub_id,))
    con.commit()
    con.close()
    return {"status": "unsubscribed", "id": sub_id}

@app.get("/api/notifications/config")
def get_smtp_config():
    cfg = _get_smtp_config()
    # Never expose password in GET
    cfg.pop("password", None)
    cfg["configured"] = bool(cfg.get("username"))
    return cfg

@app.post("/api/notifications/config")
def save_smtp_config(cfg: SmtpConfigUpdate):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        "UPDATE smtp_config SET host=?, port=?, username=?, password=?, from_name=? WHERE id=1",
        (cfg.host, cfg.port, cfg.username, cfg.password, cfg.from_name)
    )
    con.commit()
    con.close()
    return {"status": "saved", "message": "SMTP configuration updated."}

@app.post("/api/notifications/test")
def send_test_notification():
    """Send a test email to all active subscribers."""
    cfg = _get_smtp_config()
    if not cfg.get("username") or not cfg.get("password"):
        raise HTTPException(status_code=400, detail="SMTP not configured. Go to Notifications → Email Settings.")
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    subs = con.execute("SELECT * FROM subscribers WHERE enabled=1 AND email IS NOT NULL AND email != ''").fetchall()
    con.close()
    if not subs:
        raise HTTPException(status_code=404, detail="No email subscribers found. Register at least one email.")
    subject = "✅ Test Alert — Smart-Manhole System"
    html = """<html><body style='background:#0d1117;color:#e6edf3;font-family:Arial,sans-serif;padding:24px;'>
    <h2 style='color:#3fb950;'>✅ Test Notification</h2>
    <p>Your Smart-Manhole alert subscription is working correctly.</p>
    <p style='color:#8b949e;'>You will receive real-time alerts when <span style='color:#f85149;'>DANGER</span> or 
    <span style='color:#d29922;'>WARNING</span> levels are detected.</p>
    <hr style='border-color:#30363d;'/><p style='color:#555;font-size:12px;'>Smart-Manhole+ · Chennai Smart City</p>
    </body></html>"""
    text = "TEST: Your Smart-Manhole alert subscription is active and working."
    sent = 0
    for sub in subs:
        if _send_email(cfg, sub["email"], subject, html, text):
            sent += 1
    return {"status": "ok", "sent": sent, "total": len(subs)}

@app.get("/api/notifications/log")
def get_notification_log(n: int = 50):
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT * FROM notification_log ORDER BY id DESC LIMIT ?", (n,)).fetchall()
    con.close()
    return [dict(r) for r in rows]


@app.get("/")
def serve():
    return FileResponse("dashboard.html")