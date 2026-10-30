from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)

# تخزين مؤقت للبيانات في الذاكرة
patients_db = []
history_db = []

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "running", "message": "PharmaLink Server is running"})

# مسار استقبال وجلب المرضى
@app.route("/api/patients", methods=["GET", "POST"])
def handle_patients():
    if request.method == "POST":
        data = request.get_json()
        if data:
            data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            patients_db.insert(0, data)
            return jsonify({"status": "success", "message": "تم حفظ المريض بنجاح"}), 201
        return jsonify({"status": "error", "message": "بيانات غير صالحة"}), 400
    
    return jsonify(patients_db)

# مسار السجلات والعمليات
@app.route("/api/history", methods=["GET", "POST"])
def handle_history():
    if request.method == "POST":
        data = request.get_json()
        if data:
            data["timestamp"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            history_db.insert(0, data)
            return jsonify({"status": "success", "message": "تم حفظ السجل بنجاح"}), 201
        return jsonify({"status": "error", "message": "بيانات غير صالحة"}), 400
    
    return jsonify(history_db)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
