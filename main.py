import os, re, time, json, secrets, threading, math, calendar
from datetime import date, datetime
from mailer import send_mail   # الإيميلات في ملف mailer.py
from flask import Flask, request, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
DB = os.environ.get("DB_FILE", "data.json")
ADMIN_KEY = os.environ.get("ADMIN_KEY", "adminadmin08")   # غيّرو من إعدادات Render
DAY = 86400000
lock = threading.Lock()

ORD_RE = r"[A-Za-z0-9/\-]{1,30}"
EMAIL_RE = r"[^@\s]+@[^@\s]+\.[^@\s]{2,}"

def now_ms():
    return int(time.time() * 1000)

def expired(p):
    return bool(p.get("expires")) and p["expires"] < now_ms()

def add_months(ts, m):
    dt = datetime.fromtimestamp(ts / 1000)
    i = dt.month - 1 + m
    y, mo = dt.year + i // 12, i % 12 + 1
    return int(dt.replace(year=y, month=mo, day=min(dt.day, calendar.monthrange(y, mo)[1])).timestamp() * 1000)

def months(b):
    try:
        m = int(b.get("months", 0))
    except Exception:
        return 0
    return m if 1 <= m <= 120 else 0

def grant(p, m):
    now = now_ms()
    base = p["expires"] if p["status"] == "approved" and (p.get("expires") or 0) > now else now
    p["expires"], p["status"] = add_months(base, m), "approved"

def mask(e):
    return e if len(e) <= 4 else e[:2] + "*" * (len(e) - 4) + e[-2:]

def staff_of(p):
    return [{"id": p["id"], "name": p["manager"], "ord": p.get("ord", ""), "pw": p["pw"]}] + p.get("staff", [])

def ord_taken(d, o, skip=None):
    o = o.strip().lower()
    return any(x["ord"].lower() == o and x["id"] != skip for p in d["pharmacies"] for x in staff_of(p) if x["ord"])

def confirm(p, b):
    o = str(b.get("pord", "")).strip().lower()
    x = next((x for x in staff_of(p) if x["ord"] and x["ord"].lower() == o), None)
    return x if x and check_password_hash(x["pw"], str(b.get("ppw", ""))) else None

def main_only(s):
    if s.get("emp"):
        abort(403)

def load():
    try:
        with open(DB, encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {"pharmacies": [], "patients": [], "history": [], "tokens": {}}
    d.setdefault("resets", {})
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
    if not p or expired(p):
        abort(401)
    return p

def taken(d, name, skip=None):
    return any(p["name"].strip().lower() == name.strip().lower() and p["id"] != skip for p in d["pharmacies"])

def parse_drugs(b):
    raw = b.get("drugs")
    if not isinstance(raw, list):
        return []
    out = []
    for x in raw[:10]:
        try:
            n, q = str(x.get("n", "")).strip()[:80], int(x.get("q"))
        except Exception:
            return None
        if not n or not 0 < q <= 9999:
            return None
        out.append({"n": n, "q": q})
    return out

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
    email, ordn, wil = g("email").lower(), g("ord"), b.get("wilaya")
    num = lambda v: v if isinstance(v, (int, float)) else None
    if not (name and manager and address and email and ordn):
        return jsonify(error="fill"), 400
    if len(pw) < 6:
        return jsonify(error="short"), 400
    if not re.fullmatch(EMAIL_RE, email):
        return jsonify(error="email"), 400
    if not re.fullmatch(ORD_RE, ordn):
        return jsonify(error="ord"), 400
    if not (isinstance(wil, int) and 1 <= wil <= 69):
        return jsonify(error="wil"), 400
    with lock:
        d = load()
        if name.lower() == ADMIN_KEY.lower() or taken(d, name):
            return jsonify(error="exists"), 409
        if any(p.get("email") == email for p in d["pharmacies"]):
            return jsonify(error="emailx"), 409
        if ord_taken(d, ordn):
            return jsonify(error="ordx"), 409
        d["pharmacies"].append({"id": secrets.token_hex(4), "name": name, "manager": manager,
            "email": email, "wilaya": wil, "ord": ordn, "staff": [],
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
            p = emp = None
            q = next((x for x in d["pharmacies"] if x["name"].strip().lower() == name.lower()), None)
            if q and check_password_hash(q["pw"], pw):
                p = q
            else:
                for q in d["pharmacies"]:   # دخول العامل: رقم الأوردر + كلمة السر
                    e = next((e for e in q.get("staff", []) if e["ord"].lower() == name.lower()), None)
                    if e and check_password_hash(e["pw"], pw):
                        p, emp = q, e
                        break
            if not p:
                return jsonify(error="bad"), 401
            if p["status"] != "approved":
                return jsonify(error=p["status"]), 403
            if expired(p):
                return jsonify(error="expired"), 403
            s = {"role": "ph", "id": p["id"], "emp": emp["id"] if emp else None}
        tk = secrets.token_hex(24)
        d["tokens"][tk] = s
        save(d)
    return jsonify(token=tk, role="admin" if s["role"] == "admin" else "pharmacy")

# ---------- نسيت كلمة السر ----------
def find_ph(d, name):
    return next((x for x in d["pharmacies"] if x["name"].strip().lower() == name.strip().lower()), None)

@app.post("/api/forgot")
def forgot():
    b = body(); name, em = str(b.get("name", "")).strip(), str(b.get("email", "")).strip().lower()
    with lock:
        d = load(); p = find_ph(d, name)
        if not p or p["status"] != "approved" or not em or p.get("email", "").lower() != em:
            return jsonify(error="nouser"), 404   # الاسم والإيميل لازم يتطابقو
        now = now_ms(); r = d["resets"].get(p["id"], {})
        wait = 60000 - (now - r.get("sent", 0))
        if wait > 0:
            return jsonify(error="wait", wait=math.ceil(wait / 1000), email=mask(p["email"])), 429
        code = f"{secrets.randbelow(10 ** 6):06d}"
        d["resets"][p["id"]] = {"h": generate_password_hash(code), "exp": now + 600000, "sent": now, "tries": 0}
        save(d); to, pid = p["email"], p["id"]
    try:
        send_mail(to, "PharmaLink - كود التأكيد / Code de vérification",
                  f"كود التأكيد تاعك: {code}\nصالح لمدة 10 دقائق.\n\nVotre code : {code} (valable 10 minutes).")
    except Exception as e:
        print("mail error:", e)
        with lock:
            d = load(); d["resets"].pop(pid, None); save(d)
        return jsonify(error="mail"), 502
    return jsonify(ok=True, email=mask(to))

@app.post("/api/forgot/verify")
def forgot_verify():
    b = body(); code = str(b.get("code", "")).strip()
    with lock:
        d = load(); p = find_ph(d, str(b.get("name", ""))); r = d["resets"].get(p["id"]) if p else None
        if not r or r["exp"] < now_ms():
            return jsonify(error="expired"), 400
        if r["tries"] >= 5:
            d["resets"].pop(p["id"], None); save(d)
            return jsonify(error="locked"), 429
        if not re.fullmatch(r"\d{6}", code) or not check_password_hash(r["h"], code):
            r["tries"] += 1; save(d)
            return jsonify(error="code"), 400
        r["tok"], r["exp"] = secrets.token_hex(24), now_ms() + 600000
        save(d)
    return jsonify(reset=r["tok"])

@app.post("/api/forgot/reset")
def forgot_reset():
    b = body(); pw = str(b.get("password", ""))
    if len(pw) < 6:
        return jsonify(error="short"), 400
    with lock:
        d = load(); p = find_ph(d, str(b.get("name", ""))); r = d["resets"].get(p["id"]) if p else None
        if not r or r["exp"] < now_ms() or not r.get("tok") or not secrets.compare_digest(r["tok"], str(b.get("reset", ""))):
            return jsonify(error="expired"), 400
        p["pw"] = generate_password_hash(pw)
        d["resets"].pop(p["id"], None)
        d["tokens"] = {k: v for k, v in d["tokens"].items() if not (v.get("id") == p["id"] and not v.get("emp"))}
        save(d)
    return jsonify(ok=True)

# ---------- حساب الصيدلية والعاملين ----------
@app.get("/api/me")
def get_me():
    d = load(); s = sess(d, "ph"); p = me(d, s); emp = s.get("emp")
    who = next((x for x in staff_of(p) if x["id"] == (emp or p["id"])), None) or abort(401)
    return jsonify(name=p["name"], photo=p.get("photo", ""), manager=p["manager"], address=p["address"],
                   wilaya=p.get("wilaya"), email="" if emp else p.get("email", ""), ord=p.get("ord", ""),
                   expires=p.get("expires"), emp=bool(emp), who=who["name"], myord=who["ord"])

@app.post("/api/me/photo")
def set_photo():
    ph = str(body().get("photo", ""))
    if ph and not re.fullmatch(r"data:image/(jpeg|png|webp|gif);base64,[A-Za-z0-9+/=]+", ph):
        return jsonify(error="bad"), 400
    if len(ph) > 300000:
        return jsonify(error="big"), 413
    with lock:
        d = load(); s = sess(d, "ph"); main_only(s); p = me(d, s); p["photo"] = ph; save(d)
    return jsonify(ok=True)

@app.post("/api/me/ord")
def set_ord():
    o = str(body().get("ord", "")).strip()
    if not re.fullmatch(ORD_RE, o):
        return jsonify(error="ord"), 400
    with lock:
        d = load(); s = sess(d, "ph"); main_only(s); p = me(d, s)
        if ord_taken(d, o, p["id"]):
            return jsonify(error="ordx"), 409
        p["ord"] = o; save(d)
    return jsonify(ok=True)

@app.get("/api/staff")
def staff_list():
    d = load(); s = sess(d, "ph"); main_only(s); p = me(d, s)
    return jsonify([{"id": e["id"], "name": e["name"], "ord": e["ord"]} for e in p.get("staff", [])])

@app.post("/api/staff")
def staff_add():
    b = body(); name, o, pw = str(b.get("name", "")).strip()[:60], str(b.get("ord", "")).strip(), str(b.get("password", ""))
    if not name or not re.fullmatch(ORD_RE, o):
        return jsonify(error="fill"), 400
    if len(pw) < 6:
        return jsonify(error="short"), 400
    with lock:
        d = load(); s = sess(d, "ph"); main_only(s); p = me(d, s)
        if ord_taken(d, o) or o.lower() == ADMIN_KEY.lower() or taken(d, o):
            return jsonify(error="ordx"), 409
        p.setdefault("staff", []).append({"id": secrets.token_hex(4), "name": name, "ord": o, "pw": generate_password_hash(pw)})
        save(d)
    return jsonify(ok=True)

@app.post("/api/staff/delete")
def staff_del():
    eid = body().get("id")
    with lock:
        d = load(); s = sess(d, "ph"); main_only(s); p = me(d, s)
        n = len(p.get("staff", []))
        p["staff"] = [e for e in p.get("staff", []) if e["id"] != eid]
        if len(p["staff"]) == n:
            abort(404)
        d["tokens"] = {k: v for k, v in d["tokens"].items() if v.get("emp") != eid}
        save(d)
    return jsonify(ok=True)

# ---------- المرضى ----------
@app.get("/api/patients")
def patients():
    d = load(); me(d, sess(d, "ph"))
    info = {p["name"]: p for p in d["pharmacies"]}
    return jsonify([{**x, "addr": info.get(x["ph"], {}).get("address", ""),
                     "wil": x.get("wil") or info.get(x["ph"], {}).get("wilaya")} for x in d["patients"]])

@app.get("/api/history")
def history():
    d = load(); p = me(d, sess(d, "ph"))
    return jsonify([h for h in d["history"] if h["ph"] == p["name"]][-5000:])

@app.post("/api/patients")
def save_patient():
    b = body()
    f = lambda k: str(b.get(k, "")).strip()[:120]
    fn, ln, nin, dob, drug, ordn, doc = f("fn"), f("ln"), f("nin"), f("dob"), f("drug"), f("ord"), f("doc")
    drugs = parse_drugs(b)
    if drugs is None:
        return jsonify(error="qty"), 400
    if "drugs" in b and not drugs:
        return jsonify(error="fill"), 400
    if drugs:
        drug = ", ".join(f"{x['n']} ×{x['q']}" for x in drugs)
    pid = b.get("id")
    try:
        dur = int(b.get("dur", 0))
    except Exception:
        dur = 0
    if dur > 3650:
        return jsonify(error="dur"), 400
    if not (fn and ln and dob and drug and ordn and 0 < dur and isinstance(pid, int) and re.fullmatch(r"\d{18}", nin) and re.fullmatch(ORD_RE, doc)):
        return jsonify(error="fill"), 400
    with lock:
        d = load(); p = me(d, sess(d, "ph"))
        who = confirm(p, b)          # تأكيد الصيدلاني: رقم الأوردر + كلمة السر
        if not who:
            return jsonify(error="conf"), 403
        now = int(time.time() * 1000)
        active = lambda x: x["start"] + x["dur"] * DAY > now
        old = next((x for x in d["patients"] if x["id"] == pid), None)
        if any(x["ord"].lower() == ordn.lower() for x in d["patients"] if x is not old):
            return jsonify(error="ord"), 409
        if old:
            if active(old):
                return jsonify(error="active"), 409
            old.update(drug=drug, ord=ordn, dur=dur, start=now, ph=p["name"], doc=doc, by=who["name"], byord=who["ord"], wil=p.get("wilaya"))
            if drugs:
                old["drugs"] = drugs
            else:
                old.pop("drugs", None)
            k, n = "logRenew", old["fn"] + " " + old["ln"]
        else:
            same = [x for x in d["patients"] if x["nin"] == nin]
            if same and not (age(dob) < 7 and any(age(x["dob"]) >= 18 and active(x) for x in same)):
                return jsonify(error="nin"), 409
            d["patients"].append({"id": pid, "fn": fn, "ln": ln, "nin": nin, "dob": dob, "drug": drug,
                                  "ord": ordn, "dur": dur, "start": now, "ph": p["name"], "doc": doc, "by": who["name"], "byord": who["ord"],
                                  "wil": p.get("wilaya"), **({"drugs": drugs} if drugs else {})})
            k, n = "logNew", fn + " " + ln
        d["history"].append({"id": secrets.token_hex(4), "t": now, "k": k, "n": n, "ph": p["name"], "by": who["name"]})
        save(d)
    return jsonify(ok=True)

# ---------- الأدمن ----------
@app.get("/api/admin/overview")
def overview():
    d = load(); sess(d, "admin"); now = int(time.time() * 1000)
    out = []
    for p in d["pharmacies"]:
        row = {k: p.get(k) for k in ("id", "name", "manager", "address", "lat", "lng", "status", "created", "photo", "wilaya", "email", "ord", "expires")}
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
    m = months(b)
    if b["status"] == "approved" and not m:
        abort(400)                       # القبول لازم يكون معاه عدد الأشهر
    with lock:
        d = load(); sess(d, "admin"); p = find(d, b)
        if b["status"] == "approved":
            grant(p, m)
        else:
            p["status"] = "rejected"
        if b["status"] == "rejected":
            d["tokens"] = {k: v for k, v in d["tokens"].items() if v.get("id") != p["id"]}
        save(d)
    return jsonify(ok=True)

@app.post("/api/admin/renew")
def renew():
    b = body(); m = months(b)
    if not m:
        abort(400)
    with lock:
        d = load(); sess(d, "admin"); p = find(d, b)
        if p["status"] != "approved":
            abort(400)
        grant(p, m); save(d)
    return jsonify(ok=True, expires=p["expires"])

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
    wm = {p["name"]: p.get("wilaya") for p in d["pharmacies"]}
    return jsonify([{**x, "wil": x.get("wil") or wm.get(x["ph"])} for x in d["patients"]])

@app.post("/api/admin/patient/update")
def admin_patient_update():
    b = body()
    f = lambda k: str(b.get(k, "")).strip()[:120]
    fn, ln, nin, dob, drug, ordn, ph = f("fn"), f("ln"), f("nin"), f("dob"), str(b.get("drug", "")).strip()[:300], f("ord"), f("ph")
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
        if drug != x.get("drug"):
            x.pop("drugs", None)
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
