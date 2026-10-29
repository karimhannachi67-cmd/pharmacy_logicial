import os
from flask import Flask, jsonify, request
from flask_cors import CORS
import psycopg2
from datetime import datetime

app = Flask(__name__)
CORS(app)

# رابط قاعدة البيانات الذي حصلت عليه من Render
DATABASE_URL = "postgresql://first_vixe_user:9qWg6mqHqyQW4FsbJ3mwucPtQL8Oxw4x@dpg-dbhmp9mi0phs73eprab0-a.oregon-postgres.render.com/first_vixe"

# دالة لإنشاء الجدول تلقائياً إذا لم يكن موجوداً
def init_db():
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id SERIAL PRIMARY KEY,
            branch_name VARCHAR(255) NOT NULL,
            content TEXT NOT NULL,
            timestamp VARCHAR(50) NOT NULL
        )
    ''')
    conn.commit()
    cur.close()
    conn.close()

# تشغيل دالة إنشاء الجدول عند بدء السيرفر
init_db()

@app.route("/", methods=["GET"])
def index():
    return jsonify({"status": "running", "message": "السيرفر يعمل بنجاح، استخدم مسار /data للبيانات"})

@app.route("/data", methods=["POST"])
def add_data():
    data = request.get_json()
    if data and "content" in data and "branch_name" in data:
        branch = data["branch_name"]
        content = data["content"]
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        # حفظ البيانات في قاعدة البيانات السحابية
        conn = psycopg2.connect(DATABASE_URL)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO records (branch_name, content, timestamp) VALUES (%s, %s, %s)",
            (branch, content, timestamp)
        )
        conn.commit()
        cur.close()
        conn.close()
        
        return jsonify({"status": "success", "message": "تم حفظ البيانات بنجاح في السحابة"}), 201
    return jsonify({"status": "error", "message": "بيانات غير صالحة"}), 400

@app.route("/data", methods=["GET"])
def get_data():
    # جلب جميع السجلات المخزنة من قاعدة البيانات مرتبة من الأحدث للأقدم
    conn = psycopg2.connect(DATABASE_URL)
    cur = conn.cursor()
    cur.execute("SELECT branch_name, content, timestamp FROM records ORDER BY id DESC")
    rows = cur.fetchall()
    cur.close()
    conn.close()
    
    records = []
    for row in rows:
        records.append({
            "branch_name": row[0],
            "content": row[1],
            "timestamp": row[2]
        })
        
    return jsonify(records)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
