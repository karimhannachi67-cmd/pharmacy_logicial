import os, re, time, json, secrets, threading, math, calendar, requests
from datetime import date, datetime
from supabase import create_client, Client

try:
    from dci import key as dci_key  # DCI داخلي (dci.py)
    DCI_OK = True
except Exception as _e:
    DCI_OK = False
    print("dci.py ما تحملش:", _e)
    def dci_key(name):
        return "n:" + " ".join(str(name).lower().split())

from flask import Flask, request, jsonify, abort
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# إعدادات Supabase
SUPABASE_URL = "https://garjgumzcdijtqbytggz.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# إعدادات Brevo API (تستخدم BREVO_KEY كما طلبت)
BREVO_API_KEY = os.environ.get("BREVO_KEY", "")

ADMIN_KEY = os.environ.get("ADMIN_KEY", "adminadmin08")
DAY = 86400000
lock = threading.Lock()

# الجلسات، إعادة التعيين، والتسجيلات المعلقة في الذاكرة
TOKENS = {}
RESETS = {}
PENDING_REGISTRATIONS = {}  # لتخزين بيانات التسجيل مؤقتاً لحين تأكيد الرمز

ORD_RE = r"[A-Za-z0-9/\-]{1,30}"
EMAIL_RE = r"[^@\s]+@[^@\s]+\.[^@\s]{2,}"

def send_brevo_mail(to_email, subject, html_content):
    """دالة إرسال البريد الإلكتروني عبر Brevo API باستخدام الإيميل المفعل"""
    if not BREVO_API_KEY:
        print("BREVO_KEY غير معرف!")
        return False
    url = "https://api.brevo.com/v3/smtp/email"
    headers = {
        "accept": "application/json",
        "api-key": BREVO_API_KEY,
        "content-type": "application/json"
    }
    payload = {
        "sender": {"name": "PharmaLink", "email": "Pharmalink132@gmail.com"},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html_content
    }
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        print("Brevo Response Status:", res.status_code)
        print("Brevo Response Body:", res.text)
        return res.status_code in [200, 201]
    except Exception as e:
        print("خطأ أثناء الإرسال عبر Brevo:", e)
        return False

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
    return [{"id": p["id"], "name": p["manager"], "pw": p["pw"]}] + (p.get("staff") or [])

def confirm(p, b):
    n = str(b.get("pname", "")).strip().lower()
    x = next((x for x in staff_of(p) if x["name"].strip().lower() == n), None)
    return x if x and check_password_hash(x["pw"], str(b.get("ppw", ""))) else None

def main_only(s):
    if s.get("emp"):
        abort(403)

# دوال جلب البيانات من Supabase
def get_pharmacies():
    res = supabase.table("pharmacies").select("*").execute()
    return res.data or []

def get_patients():
    res = supabase.table("patients").select("*").execute()
    return res.data or []

def get_history():
    res = supabase.table("history").select("*").execute()
    data = res.data or []
    cut = now_ms() - 365 * DAY
    return [h for h in data if h.get("t", 0) >= cut]

@app.after_request
def cors(r):
    r.headers["Access-Control-Allow-Origin"] = "*"
    r.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    r.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return r

def body():
    return request.get_json(force=True, silent=True) or {}

def sess(role):
    s = TOKENS.get(request.headers.get("Authorization", "")[7:])
    if not s or s["role"] != role:
        abort(401)
    return s

def me(s):
    pharmacies = get_pharmacies()
    p = next((x for x in pharmacies if x["id"] == s["id"] and x["status"] == "approved"), None)
    if not p or expired(p):
        abort(401)
    return p

def taken(pharmacies, name, skip=None):
    return any(p["name"].strip().lower() == name.strip().lower() and p["id"] != skip for p in pharmacies)

def drug_str(drugs):
    return ", ".join(f"{x['n']} ×{x['q']}" + (f"/{x['full']}" if x["full"] > x["q"] else "") for x in drugs)

def keys_of(rec):
    if rec.get("drugs"):
        return {dci_key(x["n"]) for x in rec["drugs"]}
    return {dci_key(s.split("×")[0]) for s in str(rec.get("drug", "")).split(",") if s.strip()}

def parse_drugs(b):
    raw = b.get("drugs")
    if not isinstance(raw, list):
        return []
    out = []
    for x in raw[:10]:
        try:
            n, q = str(x.get("n", "")).strip()[:80], int(x.get("q"))
            full = int(x.get("full") or q)
        except Exception:
            return None
        if not n or not 0 < q <= 9999 or not 0 < full <= 9999:
            return None
        if q > full:
            return False
        out.append({"n": n, "q": q, "full": full})
    return out

def age(dob):
    try:
        y, m, dd = map(int, dob.split("-")); t = date.today()
        return t.year - y - ((t.month, t.day) < (m, dd))
    except Exception:
        return 0

@app.get("/")
def home():
    return "PharmaLink API OK (Supabase)"

# ---------- الحسابات والتسجيل مع Brevo ----------
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
        pharmacies = get_pharmacies()
        if name.lower() == ADMIN_KEY.lower() or taken(pharmacies, name):
            return jsonify(error="exists"), 409
        if any(p.get("email") == email for p in pharmacies):
            return jsonify(error="emailx"), 409
        if any(p.get("ord", "").lower() == ordn.lower() for p in pharmacies):
            return jsonify(error="ordx"), 409

        now = now_ms()
        pending_data = PENDING_REGISTRATIONS.get(email, {})
        if 60000 - (now - pending_data.get("sent", 0)) > 0:
            return jsonify(error="wait", wait=math.ceil((60000 - (now - pending_data.get("sent", 0))) / 1000)), 429

        code = f"{secrets.randbelow(10 ** 6):06d}"
        new_ph = {
            "id": secrets.token_hex(4), "name": name, "manager": manager,
            "email": email, "wilaya": wil, "ord": ordn, "staff": [],
            "address": address, "lat": num(b.get("lat")), "lng": num(b.get("lng")),
            "pw": generate_password_hash(pw), "status": "pending", "photo": "",
            "created": now
        }
        
        PENDING_REGISTRATIONS[email] = {
            "data": new_ph,
            "code_hash": generate_password_hash(code),
            "exp": now + 600000,
            "sent": now,
            "tries": 0
        }

    html_content = f"""
    <div style="direction: rtl; font-family: Tahoma, sans-serif; padding: 20px; border: 1px solid #d6e1e3; border-radius: 12px;">
        <h2 style="color: #0f766e;">مرحباً بك في PharmaLink</h2>
        <p>كود تأكيد البريد الإلكتروني الخاص بحسابك هو:</p>
        <h1 style="color: #0d5f58; letter-spacing: 5px; font-size: 32px; text-align: center;">{code}</h1>
        <p style="color: #5d7279; font-size: 13px;">هذا الرمز صالح لمدة 10 دقائق.</p>
    </div>
    """
    
    if not send_brevo_mail(email, "PharmaLink - كود تأكيد البريد الإلكتروني", html_content):
        with lock:
            PENDING_REGISTRATIONS.pop(email, None)
        return jsonify(error="mail"), 502

    return jsonify(ok=True, email=mask(email))

@app.post("/api/register/verify")
def register_verify():
    b = body()
    email = str(b.get("email", "")).strip().lower()
    code = str(b.get("code", "")).strip()

    with lock:
        reg = PENDING_REGISTRATIONS.get(email)
        if not reg or reg["exp"] < now_ms():
            return jsonify(error="codeExp"), 400
        if reg["tries"] >= 5:
            PENDING_REGISTRATIONS.pop(email, None)
            return jsonify(error="locked"), 429
        if not re.fullmatch(r"\d{6}", code) or not check_password_hash(reg["code_hash"], code):
            reg["tries"] += 1
            return jsonify(error="codeBad"), 400

        # حفظ الحساب رسمياً في Supabase عند نجاح الكود
        pharmacy_data = reg["data"]
        supabase.table("pharmacies").insert(pharmacy_data).execute()
        PENDING_REGISTRATIONS.pop(email, None)

    return jsonify(ok=True)

@app.get("/api/ping")
def ping():
    return jsonify(ok=True, brevo=bool(BREVO_API_KEY), dci=DCI_OK)

@app.post("/api/login")
def login():
    b = body()
    name, pw = str(b.get("name", "")).strip(), str(b.get("password", ""))
    with lock:
        pharmacies = get_pharmacies()
        if name == ADMIN_KEY:
            s = {"role": "admin", "id": None}
        else:
            p = emp = None
            q = next((x for x in pharmacies if x["name"].strip().lower() == name.lower()), None)
            if q and check_password_hash(q["pw"], pw):
                p = q
            else:
                for q in pharmacies:
                    e = next((e for e in (q.get("staff") or []) if e["name"].strip().lower() == name.lower()), None)
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
        TOKENS[tk] = s
    return jsonify(token=tk, role="admin" if s["role"] == "admin" else "pharmacy")

# ---------- نسيت كلمة السر عبر Brevo ----------
def find_ph(pharmacies, name):
    return next((x for x in pharmacies if x["name"].strip().lower() == name.strip().lower()), None)

@app.post("/api/forgot")
def forgot():
    b = body(); name, em = str(b.get("name", "")).strip(), str(b.get("email", "")).strip().lower()
    with lock:
        pharmacies = get_pharmacies(); p = find_ph(pharmacies, name)
        if not p or p["status"] != "approved":
            return jsonify(error="nouser"), 404
        if not p.get("email"):
            return jsonify(error="noemail"), 400
        if not em or p["email"].lower() != em:
            return jsonify(error="nouser"), 404
        now = now_ms(); r = RESETS.get(p["id"], {})
        wait = 60000 - (now - r.get("sent", 0))
        if wait > 0:
            return jsonify(error="wait", wait=math.ceil(wait / 1000), email=mask(p["email"])), 429
        code = f"{secrets.randbelow(10 ** 6):06d}"
        RESETS[p["id"]] = {"h": generate_password_hash(code), "exp": now + 600000, "sent": now, "tries": 0}
        to, pid = p["email"], p["id"]
    
    html_content = f"كود التأكيد تاعك: <b>{code}</b><br>صالح لمدة 10 دقائق.<br><br>Votre code : <b>{code}</b> (valable 10 minutes)."
    if not send_brevo_mail(to, "PharmaLink - كود التأكيد / Code de vérification", html_content):
        with lock:
            RESETS.pop(pid, None)
        return jsonify(error="mail"), 502

    return jsonify(ok=True, email=mask(to))

@app.post("/api/forgot/verify")
def forgot_verify():
    b = body(); code = str(b.get("code", "")).strip()
    with lock:
        pharmacies = get_pharmacies(); p = find_ph(pharmacies, str(b.get("name", ""))); r = RESETS.get(p["id"]) if p else None
        if not r or r["exp"] < now_ms():
            return jsonify(error="expired"), 400
        if r["tries"] >= 5:
            RESETS.pop(p["id"], None)
            return jsonify(error="locked"), 429
        if not re.fullmatch(r"\d{6}", code) or not check_password_hash(r["h"], code):
            r["tries"] += 1
            return jsonify(error="code"), 400
        r["tok"], r["exp"] = secrets.token_hex(24), now_ms() + 600000
    return jsonify(reset=r["tok"])

@app.post("/api/forgot/reset")
def forgot_reset():
    b = body(); pw = str(b.get("password", ""))
    if len(pw) < 6:
        return jsonify(error="short"), 400
    with lock:
        pharmacies = get_pharmacies(); p = find_ph(pharmacies, str(b.get("name", ""))); r = RESETS.get(p["id"]) if p else None
        if not r or r["exp"] < now_ms() or not r.get("tok") or not secrets.compare_digest(r["tok"], str(b.get("reset", ""))):
            return jsonify(error="expired"), 400
        new_pw = generate_password_hash(pw)
        supabase.table("pharmacies").update({"pw": new_pw}).eq("id", p["id"]).execute()
        RESETS.pop(p["id"], None)
        global TOKENS
        TOKENS = {k: v for k, v in TOKENS.items() if not (v.get("id") == p["id"] and not v.get("emp"))}
    return jsonify(ok=True)

# ---------- حساب الصيدلية والعاملين ----------
@app.get("/api/me")
def get_me():
    s = sess("ph"); p = me(s); emp = s.get("emp")
    who = next((x for x in staff_of(p) if x["id"] == (emp or p["id"])), None) or abort(401)
    return jsonify(name=p["name"], photo=p.get("photo", ""), manager=p["manager"], address=p["address"],
                   wilaya=p.get("wilaya"), email="" if emp else p.get("email", ""), ord=p.get("ord", ""),
                   expires=p.get("expires"), emp=bool(emp), who=who["name"])

@app.post("/api/me/photo")
def set_photo():
    ph = str(body().get("photo", ""))
    if ph and not re.fullmatch(r"data:image/(jpeg|png|webp|gif);base64,[A-Za-z0-9+/=]+", ph):
        return jsonify(error="bad"), 400
    if len(ph) > 300000:
        return jsonify(error="big"), 413
    s = sess("ph"); main_only(s); p = me(s)
    supabase.table("pharmacies").update({"photo": ph}).eq("id", p["id"]).execute()
    return jsonify(ok=True)

@app.get("/api/staff")
def staff_list():
    s = sess("ph"); main_only(s); p = me(s)
    return jsonify([{"id": e["id"], "name": e["name"]} for e in (p.get("staff") or [])])

@app.post("/api/staff")
def staff_add():
    b = body(); name, pw = str(b.get("name", "")).strip()[:60], str(b.get("password", ""))
    if not name:
        return jsonify(error="fill"), 400
    if len(pw) < 6:
        return jsonify(error="short"), 400
    with lock:
        pharmacies = get_pharmacies(); s = sess("ph"); main_only(s); p = me(s)
        nm = name.lower()
        if nm == ADMIN_KEY.lower() or taken(pharmacies, name) or any(
                nm in (q["manager"].strip().lower(), *[e["name"].strip().lower() for e in (q.get("staff") or [])])
                for q in pharmacies):
            return jsonify(error="namex"), 409
        staff_list_val = p.get("staff") or []
        staff_list_val.append({"id": secrets.token_hex(4), "name": name, "pw": generate_password_hash(pw)})
        supabase.table("pharmacies").update({"staff": staff_list_val}).eq("id", p["id"]).execute()
    return jsonify(ok=True)

@app.post("/api/staff/delete")
def staff_del():
    eid = body().get("id")
    with lock:
        s = sess("ph"); main_only(s); p = me(s)
        staff_list_val = p.get("staff") or []
        n = len(staff_list_val)
        new_staff = [e for e in staff_list_val if e["id"] != eid]
        if len(new_staff) == n:
            abort(404)
        supabase.table("pharmacies").update({"staff": new_staff}).eq("id", p["id"]).execute()
        global TOKENS
        TOKENS = {k: v for k, v in TOKENS.items() if v.get("emp") != eid}
    return jsonify(ok=True)

# ---------- المرضى ----------
@app.get("/api/patients")
def patients():
    me(sess("ph"))
    pharmacies = get_pharmacies()
    patients_data = get_patients()
    info = {p["name"]: p for p in pharmacies}
    return jsonify([{**x, "addr": info.get(x["ph"], {}).get("address", ""),
                     "wil": x.get("wil") or info.get(x["ph"], {}).get("wilaya")} for x in patients_data])

@app.get("/api/history")
def history():
    p = me(sess("ph"))
    hist = get_history()
    return jsonify([h for h in hist if h["ph"] == p["name"]][-5000:])

@app.post("/api/patients")
def save_patient():
    b = body()
    f = lambda k: str(b.get(k, "")).strip()[:120]
    fn, ln, nin, dob, drug, ordn, doc = f("fn"), f("ln"), f("nin"), f("dob"), f("drug"), f("ord"), f("doc")
    drugs = parse_drugs(b)
    if drugs is False:
        return jsonify(error="full"), 400
    if drugs is None:
        return jsonify(error="qty"), 400
    if "drugs" in b and not drugs:
        return jsonify(error="fill"), 400
    if drugs:
        if len({dci_key(x["n"]) for x in drugs}) < len(drugs):
            return jsonify(error="dup"), 400
        drug = drug_str(drugs)
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
        pharmacies = get_pharmacies(); p = me(sess("ph"))
        who = confirm(p, b)
        if not who:
            return jsonify(error="conf"), 403
        now = now_ms()
        active = lambda x: x["start"] + x["dur"] * DAY > now
        patients_data = get_patients()
        old = next((x for x in patients_data if x["id"] == pid), None)
        if any(x["ord"].lower() == ordn.lower() for x in patients_data if x is not old):
            return jsonify(error="ord"), 409
        newkeys = keys_of({"drugs": drugs} if drugs else {"drug": drug})

        def clash(pn, pdob, skip):
            for x in patients_data:
                if x is skip or x["nin"] != pn or x["dob"] != pdob or not active(x):
                    continue
                hit = newkeys & keys_of(x)
                if hit:
                    return next((y["n"] for y in drugs if dci_key(y["n"]) in hit), "") if drugs else ""
            return None

        if old:
            if active(old):
                return jsonify(error="active"), 409
            hit = clash(old["nin"], old["dob"], old)
            if hit is not None:
                return jsonify(error="dci", drug=hit), 409
            
            up_data = {
                "drug": drug, "ord": ordn, "dur": dur, "start": now, 
                "ph": p["name"], "doc": doc, "by": who["name"], 
                "wil": p.get("wilaya"), "pord": p.get("ord", ""),
                "drugs": drugs if drugs else None
            }
            supabase.table("patients").update(up_data).eq("id", pid).execute()
            k, n = "logRenew", old["fn"] + " " + old["ln"]
        else:
            same = [x for x in patients_data if x["nin"] == nin]
            child = age(dob) < 7 and any(age(x["dob"]) >= 18 and active(x) for x in same)
            if same and not (child or any(x["dob"] == dob for x in same)):
                return jsonify(error="nin"), 409
            hit = clash(nin, dob, None)
            if hit is not None:
                return jsonify(error="dci", drug=hit), 409
            
            new_patient = {
                "id": pid, "fn": fn, "ln": ln, "nin": nin, "dob": dob, "drug": drug,
                "ord": ordn, "dur": dur, "start": now, "ph": p["name"], "doc": doc, "by": who["name"],
                "wil": p.get("wilaya"), "pord": p.get("ord", ""), **({"drugs": drugs} if drugs else {})
            }
            supabase.table("patients").insert(new_patient).execute()
            k, n = "logNew", fn + " " + ln
            
        new_history = {"id": secrets.token_hex(4), "t": now, "k": k, "n": n, "ph": p["name"], "by": who["name"]}
        supabase.table("history").insert(new_history).execute()
    return jsonify(ok=True)

@app.post("/api/patients/complete")
def complete_patient():
    b = body(); pid = b.get("id")
    try:
        adds = [int(a) for a in b.get("adds")]
    except Exception:
        return jsonify(error="fill"), 400
    if not isinstance(pid, int) or any(a < 0 for a in adds) or not any(adds):
        return jsonify(error="fill"), 400
    with lock:
        p = me(sess("ph"))
        who = confirm(p, b)
        if not who:
            return jsonify(error="conf"), 403
        now = now_ms()
        patients_data = get_patients()
        x = next((x for x in patients_data if x["id"] == pid), None)
        if not x or not x.get("drugs") or len(adds) != len(x["drugs"]):
            abort(404)
        if x["start"] + x["dur"] * DAY <= now:
            return jsonify(error="expired"), 409
        for dr in x["drugs"]:
            dr.setdefault("full", dr["q"])
        if any(a > dr["full"] - dr["q"] for a, dr in zip(adds, x["drugs"])):
            return jsonify(error="over"), 400
        for a, dr in zip(adds, x["drugs"]):
            dr["q"] += a
        new_drug_str = drug_str(x["drugs"])
        
        supabase.table("patients").update({"drugs": x["drugs"], "drug": new_drug_str}).eq("id", pid).execute()
        new_history = {"id": secrets.token_hex(4), "t": now, "k": "logDone", "n": x["fn"] + " " + x["ln"],
                       "ph": p["name"], "by": who["name"]}
        supabase.table("history").insert(new_history).execute()
    return jsonify(ok=True)

# ---------- الأدمن ----------
@app.get("/api/admin/overview")
def overview():
    sess("admin"); now = now_ms()
    pharmacies = get_pharmacies()
    patients_data = get_patients()
    history_data = get_history()
    out = []
    for p in pharmacies:
        row = {k: p.get(k) for k in ("id", "name", "manager", "address", "lat", "lng", "status", "created", "photo", "wilaya", "email", "ord", "expires")}
        row["patients"] = sum(1 for x in patients_data if x["ph"] == p["name"])
        row["ops"] = sum(1 for h in history_data if h["ph"] == p["name"])
        out.append(row)
    return jsonify(pharmacies=out, patients=len(patients_data),
                   today=sum(1 for h in history_data if now - h["t"] < DAY))

def find(pharmacies, b):
    return next((x for x in pharmacies if x["id"] == b.get("id")), None) or abort(404)

@app.post("/api/admin/status")
def set_status():
    b = body()
    if b.get("status") not in ("approved", "rejected"):
        abort(400)
    m = months(b)
    if b["status"] == "approved" and not m:
        abort(400)
    with lock:
        pharmacies = get_pharmacies(); sess("admin"); p = find(pharmacies, b)
        if b["status"] == "approved":
            grant(p, m)
            supabase.table("pharmacies").update({"status": "approved", "expires": p["expires"]}).eq("id", p["id"]).execute()
        else:
            supabase.table("pharmacies").update({"status": "rejected"}).eq("id", p["id"]).execute()
            global TOKENS
            TOKENS = {k: v for k, v in TOKENS.items() if v.get("id") != p["id"]}
    return jsonify(ok=True)

@app.post("/api/admin/renew")
def renew():
    b = body(); m = months(b)
    if not m:
        abort(400)
    with lock:
        pharmacies = get_pharmacies(); sess("admin"); p = find(pharmacies, b)
        if p["status"] != "approved":
            abort(400)
        grant(p, m)
        supabase.table("pharmacies").update({"expires": p["expires"]}).eq("id", p["id"]).execute()
    return jsonify(ok=True, expires=p["expires"])

@app.post("/api/admin/email")
def admin_email():
    b = body(); em = str(b.get("email", "")).strip().lower()
    if not re.fullmatch(EMAIL_RE, em):
        abort(400)
    with lock:
        pharmacies = get_pharmacies(); sess("admin"); p = find(pharmacies, b)
        if any(x.get("email") == em and x["id"] != p["id"] for x in pharmacies):
            return jsonify(error="emailx"), 409
        supabase.table("pharmacies").update({"email": em}).eq("id", p["id"]).execute()
    return jsonify(ok=True)

@app.post("/api/admin/rename")
def rename():
    b = body(); new = str(b.get("name", "")).strip()[:120]
    if not new:
        abort(400)
    with lock:
        pharmacies = get_pharmacies(); sess("admin"); p = find(pharmacies, b)
        if new.lower() == ADMIN_KEY.lower() or taken(pharmacies, new, p["id"]):
            return jsonify(error="exists"), 409
        old, name_val = p["name"], new
        supabase.table("pharmacies").update({"name": name_val}).eq("id", p["id"]).execute()
        
        patients_data = get_patients()
        for x in patients_data:
            if x["ph"] == old:
                supabase.table("patients").update({"ph": name_val}).eq("id", x["id"]).execute()
        history_data = get_history()
        for h in history_data:
            if h["ph"] == old:
                supabase.table("history").update({"ph": name_val}).eq("id", h["id"]).execute()
    return jsonify(ok=True)

@app.get("/api/admin/patients")
def admin_patients():
    sess("admin")
    pharmacies = get_pharmacies()
    patients_data = get_patients()
    wm = {p["name"]: p.get("wilaya") for p in pharmacies}
    return jsonify([{**x, "wil": x.get("wil") or wm.get(x["ph"])} for x in patients_data])

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
        pharmacies = get_pharmacies(); sess("admin")
        patients_data = get_patients()
        x = next((x for x in patients_data if x["id"] == b.get("id")), None) or abort(404)
        if not any(p["name"] == ph for p in pharmacies):
            return jsonify(error="fill"), 400
        if any(y["ord"].lower() == ordn.lower() for y in patients_data if y is not x):
            return jsonify(error="ord"), 409
        
        up_data = {
            "fn": fn, "ln": ln, "nin": nin, "dob": dob, 
            "drug": drug, "ord": ordn, "dur": dur, "start": start, "ph": ph
        }
        if drug != x.get("drug"):
            up_data["drugs"] = None
        supabase.table("patients").update(up_data).eq("id", x["id"]).execute()
    return jsonify(ok=True)

@app.post("/api/admin/patient/delete")
def admin_patient_delete():
    b = body()
    with lock:
        sess("admin")
        supabase.table("patients").delete().eq("id", b.get("id")).execute()
    return jsonify(ok=True)

@app.get("/api/admin/history")
def a_history():
    sess("admin")
    history_data = get_history()
    for h in history_data:
        if "id" not in h or not h["id"]:
            new_id = secrets.token_hex(4)
            supabase.table("history").update({"id": new_id}).eq("t", h["t"]).execute()
            h["id"] = new_id
    return jsonify(history_data)

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
        pharmacies = get_pharmacies(); sess("admin")
        history_data = get_history()
        h = next((x for x in history_data if x.get("id"] == b.get("id")), None) or abort(404)
        if not any(p["name"] == b.get("ph") for p in pharmacies):
            return jsonify(error="fill"), 400
        supabase.table("history").update({"t": tm, "k": b["k"], "n": n, "ph": b["ph"]}).eq("id", h["id"]).execute()
    return jsonify(ok=True)

@app.post("/api/admin/history/delete")
def a_history_delete():
    b = body()
    with lock:
        sess("admin")
        supabase.table("history").delete().eq("id", b.get("id")).execute()
    return jsonify(ok=True)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))
