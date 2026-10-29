from flask import Flask, jsonify, request

app = Flask(name)

# متغير لتخزين الكلمة أو البيانات مؤقتاً للتجربة
latest_word = "لا توجد بيانات بعد"

@app.route("/", methods=["GET", "POST"])
def home():
    global latest_word
    if request.method == "POST":
        data = request.get_json()
        if data and "word" in data:
            latest_word = data["word"]
            return jsonify({"status": "success", "message": "تم الحفظ بنجاح"})
        return jsonify({"status": "error", "message": "بيانات غير صالحة"}), 400
    
    # في حال طلب GET على الصفحة الرئيسية أو كـ API
    return jsonify({"status": "success", "latest_words": latest_word})

if name == "main":
    app.run(host="0.0.0.0", port=5000)
