from flask import Flask, jsonify, request
from flask_cors import CORS
from datetime import datetime

app = Flask(__name__)
CORS(app)  # السماح بالاتصال الخارجي

# تخزين مؤقت للبيانات في الذاكرة (بدون قاعدة بيانات مؤقتاً)
database_records = []

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "running", "message": "السيرفر يعمل بنجاح بدون قاعدة بيانات، استخدم مسار /data للبيانات"})

@app.route("/data", methods=["POST"])
def add_data():
    data = request.get_json()
    if data and "content" in data and "branch_name" in data:
        branch = data["branch_name"]
        content = data["content"]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # حفظ البيانات في القائمة المؤقتة بالذاكرة
        record = {
            "branch_name": branch,
            "content": content,
            "timestamp": timestamp
        }
        database_records.insert(0, record)  # الإضافة في البداية لتكون الأحدث في الأعلى
        
        return jsonify({"status": "success", "message": "تم حفظ البيانات بنجاح في الذاكرة المؤقتة"}), 201
    return jsonify({"status": "error", "message": "بيانات غير صالحة"}), 400

@app.route("/data", methods=["GET"])
def get_data():
    # إرجاع كافة السجلات المخزنة مؤقتاً في الذاكرة
    return jsonify(database_records)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
