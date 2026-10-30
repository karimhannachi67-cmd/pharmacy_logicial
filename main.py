from flask import Flask, jsonify, request
from flask_cors import CORS
import time

app = Flask(__name__)
# تفعيل الـ CORS لسماح الاتصال بالتطبيق
CORS(app)

# قواعد بيانات مؤقتة للتشغيل التجريبي
patients_db = [
    {"id": 1, "fn": "محمد", "ln": "بوزيدي", "nin": "109876543210123456", "dob": "1985-04-12", "drug": "Alprazolam", "ord": "A-1042", "start": time.time() - (10 * 86400), "dur": 30, "ph": "me"},
    {"id": 2, "fn": "فاطمة", "ln": "قاسمي", "nin": "209876543210123457", "dob": "1990-09-02", "drug": "Clonazepam", "ord": "B-220", "start": time.time() - (45 * 86400), "dur": 30, "ph": "Pharmacie Ennour"},
    {"id": 3, "fn": "يوسف", "ln": "مرابط", "nin": "309876543210123458", "dob": "1978-01-25", "drug": "Diazepam", "ord": "C-77", "start": time.time() - (3 * 86400), "dur": 14, "ph": "Pharmacie El Amel"}
]

history_db = [
    {"t": time.time() - (2 * 86400), "k": "logNew", "n": "محمد بوزيدي"},
    {"t": time.time() - (9 * 86400), "k": "logNew", "n": "سعاد حداد"}
]

current_id = 10

@app.route("/api/patients", methods=["GET"])
def get_patients():
    return jsonify(patients_db)

@app.route("/api/patients", methods=["POST"])
def add_patient():
    global current_id
    data = request.json
    
    new_patient = {
        "id": current_id,
        "fn": data.get("fn"),
        "ln": data.get("ln"),
        "nin": data.get("nin"),
        "dob": data.get("dob"),
        "drug": data.get("drug"),
        "ord": data.get("ord"),
        "start": data.get("start", time.time()),
        "dur": data.get("dur"),
        "ph": data.get("ph", "me")
    }
    current_id += 1
    patients_db.append(new_patient)
    
    # إضافة للسجل
    history_db.insert(0, {"t": time.time(), "k": "logNew", "n": f"{new_patient['fn']} {new_patient['ln']}"})
    return jsonify({"status": "success", "id": new_patient["id"]}), 201

@app.route("/api/patients/<int:patient_id>", methods=["PUT"])
def update_patient(patient_id):
    data = request.json
    for p in patients_db:
        if p["id"] == patient_id:
            p.update({
                "drug": data.get("drug", p["drug"]),
                "ord": data.get("ord", p["ord"]),
                "dur": data.get("dur", p["dur"]),
                "start": time.time(),
                "ph": data.get("ph", "me")
            })
            history_db.insert(0, {"t": time.time(), "k": "logRenew", "n": f"{p['fn']} {p['ln']}"})
            return jsonify({"status": "success"})
            
    return jsonify({"error": "Patient not found"}), 404

@app.route("/api/history", methods=["GET"])
def get_history():
    return jsonify(history_db)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
