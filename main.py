import os, re, time, json, secrets, threading
from datetime import date
from flask import Flask, request, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
DB = os.environ.get("DB_FILE", "data.json")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "adminadmin08")   # غيّرو من إعدادات Render
DAY = 86400000
lock = threading.Lock()

def load():
    try:
        with open(DB, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {"pharmacies": [], "patients": [], "history": [], "tokens": {}}
    cut = int(time.time() * 1000) - 365 * DAY          # السجل يُحتفظ به سنة فقط
    d["history"] = [h for h in d["history"] if h["t"] >= cut]
    return d

def save(d):
    with open(DB, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False)

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return r

def body():
    return request.get_json(force=True, silent=True) or {}

def sess(d, role):
    s = d["tokens"].get(request.headers.get("Authorization", "")[7:])
    if not s or s["role"] != role:
        abort(401)
    return s

def me(d, s):
    p = next((x for x in d["pharmacies"] if x["id"] == s["id"] and x["status"] == "approved"), None)
    return p or abort(401)

def taken(d, name, skip=None):
    return any(p["name"].strip().lower() == name.strip().lower() and p["id"] != skip for p in d["pharmacies"])

def age(dob):
    try:
        y, m, dd = map(int, dob.split("-")); t = date.today()
        return t.year - y - ((t.month, t.day) < (m, dd))
    except Exception:
        return 0

@app.get("/")
def home():
    return "PharmaLink API OK"

# ---------- الحسابات ----------
@app.post("/api/register")
def register():
    b = body()
    g = lambda k: str(b.get(k, "")).strip()[:120]
    name, manager, address, pw = g("name"), g("manager"), g("address"), str(b.get("password", ""))
    num = lambda v: v if isinstance(v, (int, float)) else None
    if not (name and manager and address):
        return jsonify(error="fill"), 400
    if len(pw) < 6:
        return jsonify(error="short"), 400
    with lock:
        d = load()
        if name.lower() == ADMIN_KEY.lower() or taken(d, name):
            return jsonify(error="exists"), 409
        d["pharmacies"].append({"id": secrets.token_hex(4), "name": name, "manager": manager,
            "address": address, "lat": num(b.get("lat")), "lng": num(b.get("lng")),
            "pw": generate_password_hash(pw), "status": "pending", "photo": "",
            "created": int(time.time() * 1000)})
        save(d)
    return jsonify(ok=True)

@app.post("/api/login")
def login():
    b = body()
    name, pw = str(b.get("name", "")).strip(), str(b.get("password", ""))
    with lock:
        d = load()
        if name == ADMIN_KEY:
            s = {"role": "admin", "id": None}
        else:
            p = next((x for x in d["pharmacies"] if x["name"].strip().lower() == name.lower()), None)
            if not p or not check_password_hash(p["pw"], pw):
                return jsonify(error="bad"), 401
            if p["status"] != "approved":
                return jsonify(error=p["status"]), 403
            s = {"role": "ph", "id": p["id"]}
        tk = secrets.token_hex(24)
        d["tokens"][tk] = s
        save(d)
    return jsonify(token=tk, role="admin" if s["role"] == "admin" else "pharmacy")

@app.get("/api/me")
def get_me():
    d = load(); p = me(d, sess(d, "ph"))
    return jsonify(name=p["name"], photo=p.get("photo", ""), manager=p["manager"], address=p["address"])

@app.post("/api/me/photo")
def set_photo():
    ph = str(body().get("photo", ""))
    if ph and not re.fullmatch(r"data:image/(jpeg|png|webp|gif);base64,[A-Za-z0-9+/=]+", ph):
        return jsonify(error="bad"), 400
    if len(ph) > 300000:
        return jsonify(error="big"), 413
    with lock:
        d = load(); p = me(d, sess(d, "ph")); p["photo"] = ph; save(d)
    return jsonify(ok=True)

# ---------- المرضى ----------
@app.get("/api/patients")
def patients():
    d = load(); me(d, sess(d, "ph"))
    addr = {p["name"]: p["address"] for p in d["pharmacies"]}
    return jsonify([{**x, "addr": addr.get(x["ph"], "")} for x in d["patients"]])

@app.get("/api/history")
def history():
    d = load(); p = me(d, sess(d, "ph"))
    return jsonify([h for h in d["history"] if h["ph"] == p["name"]][-5000:])

@app.post("/api/patients")
def save_patient():
    b = body()
    f = lambda k: str(b.get(k, "")).strip()[:120]
    fn, ln, nin, dob, drug, ordn = f("fn"), f("ln"), f("nin"), f("dob"), f("drug"), f("ord")
    pid = b.get("id")
    try:
        dur = int(b.get("dur", 0))
    except Exception:
        dur = 0
    if not (fn and ln and dob and drug and ordn and 0 < dur <= 3650 and isinstance(pid, int) and re.fullmatch(r"\d{18}", nin)):
        return jsonify(error="fill"), 400
    with lock:
        d = load(); p = me(d, sess(d, "ph"))
        now = int(time.time() * 1000)
        active = lambda x: x["start"] + x["dur"] * DAY > now
        old = next((x for x in d["patients"] if x["id"] == pid), None)
        if any(x["ord"].lower() == ordn.lower() for x in d["patients"] if x is not old):
            return jsonify(error="ord"), 409
        if old:
            if active(old):
                return jsonify(error="active"), 409
            old.update(drug=drug, ord=ordn, dur=dur, start=now, ph=p["name"])
            k, n = "logRenew", old["fn"] + " " + old["ln"]
        else:
            same = [x for x in d["patients"] if x["nin"] == nin]
            if same and not (age(dob) < 7 and any(age(x["dob"]) >= 18 and active(x) for x in same)):
                return jsonify(error="nin"), 409
            d["patients"].append({"id": pid, "fn": fn, "ln": ln, "nin": nin, "dob": dob, "drug": drug,
                                  "ord": ordn, "dur": dur, "start": now, "ph": p["name"]})
            k, n = "logNew", fn + " " + ln
        d["history"].append({"id": secrets.token_hex(4), "t": now, "k": k, "n": n, "ph": p["name"]})
        save(d)
    return jsonify(ok=True)

# ---------- الأدمن ----------
@app.get("/api/admin/overview")
def overview():
    d = load(); sess(d, "admin"); now = int(time.time() * 1000)
    out = []
    for p in d["pharmacies"]:
        row = {k: p.get(k) for k in ("id", "name", "manager", "address", "lat", "lng", "status", "created", "photo")}
        row["patients"] = sum(1 for x in d["patients"] if x["ph"] == p["name"])
        row["ops"] = sum(1 for h in d["history"] if h["ph"] == p["name"])
        out.append(row)
    return jsonify(pharmacies=out, patients=len(d["patients"]),
                   today=sum(1 for h in d["history"] if now - h["t"] < DAY))

def find(d, b):
    return next((x for x in d["pharmacies"] if x["id"] == b.get("id")), None) or abort(404)

@app.post("/api/admin/status")
def set_status():
    b = body()
    if b.get("status") not in ("approved", "rejected"):
        abort(400)
    with lock:
        d = load(); sess(d, "admin"); p = find(d, b)
        p["status"] = b["status"]
        if b["status"] == "rejected":
            d["tokens"] = {k: v for k, v in d["tokens"].items() if v.get("id") != p["id"]}
        save(d)
    return jsonify(ok=True)

@app.post("/api/admin/rename")
def rename():
    b = body(); new = str(b.get("name", "")).strip()[:120]
    if not new:
        abort(400)
    with lock:
        d = load(); sess(d, "admin"); p = find(d, b)
        if new.lower() == ADMIN_KEY.lower() or taken(d, new, p["id"]):
            return jsonify(error="exists"), 409
        old, p["name"] = p["name"], new
        for x in d["patients"] + d["history"]:
            if x["ph"] == old:
                x["ph"] = new
        save(d)
    return jsonify(ok=True)

@app.get("/api/admin/patients")
def admin_patients():
    d = load(); sess(d, "admin")
    return jsonify(d["patients"])

@app.post("/api/admin/patient/update")
def admin_patient_update():
    b = body()
    f = lambda k: str(b.get(k, "")).strip()[:120]
    fn, ln, nin, dob, drug, ordn, ph = f("fn"), f("ln"), f("nin"), f("dob"), f("drug"), f("ord"), f("ph")
    try:
        dur, start = int(b.get("dur", 0)), int(b.get("start", 0))
    except Exception:
        dur = start = 0
    if not (fn and ln and dob and drug and ordn and ph and 0 < dur <= 3650 and start > 0 and re.fullmatch(r"\d{18}", nin)):
        return jsonify(error="fill"), 400
    with lock:
        d = load(); sess(d, "admin")
        x = next((x for x in d["patients"] if x["id"] == b.get("id")), None) or abort(404)
        if not any(p["name"] == ph for p in d["pharmacies"]):
            return jsonify(error="fill"), 400
        if any(y["ord"].lower() == ordn.lower() for y in d["patients"] if y is not x):
            return jsonify(error="ord"), 409
        x.update(fn=fn, ln=ln, nin=nin, dob=dob, drug=drug, ord=ordn, dur=dur, start=start, ph=ph)
        save(d)
    return jsonify(ok=True)

@app.post("/api/admin/patient/delete")
def admin_patient_delete():
    b = body()
    with lock:
        d = load(); sess(d, "admin")
        n = len(d["patients"])
        d["patients"] = [x for x in d["patients"] if x["id"] != b.get("id")]
        if len(d["patients"]) == n:
            abort(404)
        save(d)
    return jsonify(ok=True)

@app.get("/api/admin/history")
def a_history():
    with lock:
        d = load(); sess(d, "admin")
        if any("id" not in h for h in d["history"]):
            for h in d["history"]:
                h.setdefault("id", secrets.token_hex(4))
            save(d)
    return jsonify(d["history"])

@app.post("/api/admin/history/update")
def a_history_update():
    b = body()
    try:
        tm = int(b.get("t"))
    except Exception:
        tm = 0
    n = str(b.get("n", "")).strip()[:120]
    if not (tm > 0 and n and b.get("k") in ("logNew", "logRenew")):
        return jsonify(error="fill"), 400
    with lock:
        d = load(); sess(d, "admin")
        h = next((x for x in d["history"] if x.get("id") == b.get("id")), None) or abort(404)
        if not any(p["name"] == b.get("ph") for p in d["pharmacies"]):
            return jsonify(error="fill"), 400
        h.update(t=tm, k=b["k"], n=n, ph=b["ph"]); save(d)
    return jsonify(ok=True)

@app.post("/api/admin/history/delete")
def a_history_delete():
    b = body()
    with lock:
        d = load(); sess(d, "admin")
        h = next((x for x in d["history"] if x.get("id") == b.get("id")), None) or abort(404)
        d["history"].remove(h); save(d)
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
