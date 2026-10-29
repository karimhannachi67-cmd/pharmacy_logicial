from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(name)
CORS(app)  # تفعيل السماح بالاتصال من تطبيقات الواجهة الأمامية

# متغير مؤقت لتخزين آخر كلمة مرسلة
latest_data = {"latest_word": "لا توجد كلمات بعد"}

@app.route("/", methods=["GET", "POST"])
def home():
    global latest_data
    if request.method == "POST":
        data = request.get_json()
        if data and "word" in data:
            latest_data["latest_word"] = data["word"]
            return jsonify({"status": "success", "message": "تم الحفظ بنجاح"})
        return jsonify({"status": "error", "message": "بيانات غير صالحة"}), 400
    
    # في حال طلب GET (جلب البيانات)
    return jsonify(latest_data)

if name == "main":
    app.run(host="0.0.0.0", port=5000)
