from flask import Flask, jsonify, request
from flask_cors import CORS

app = Flask(name)
CORS(app)

# متغير مؤقت لتخزين الكلمة
latest_data = {"latest_word": "لا توجد كلمات بعد"}

@app.route("/api/word", methods=["GET", "POST"])
def handle_word():
    global latest_data
    if request.method == "POST":
        data = request.get_json()
        if data and "word" in data:
            latest_data["latest_word"] = data["word"]
            return jsonify({"status": "success", "message": "تم الحفظ بنجاح"})
        return jsonify({"status": "error", "message": "بيانات غير صالحة"}), 400
    
    return jsonify(latest_data)

if name == "main":
    app.run(host="0.0.0.0", port=5000)
