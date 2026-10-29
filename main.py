from flask import Flask, jsonify, request

app = Flask(__name__)

# صفحة تجريبية للتأكد من أن السيرفر يعمل
@app.route("/")
def home():
    return jsonify({"status": "success", "message": "Mahalat Platform Server is running!"})

# يمكنك إضافة مسارات (Routes) الخاصة بمشروعك هنا
# مثال: مسار لجلب المنتجات أو بيانات الصيدلية/المحل
@app.route("/api/data", methods=["GET"])
def get_data():
    # ضع منطق قاعدة البيانات أو البيانات الخاصة بك هنا
    return jsonify({"data": []})

if __name__ == "__main__":
    # تشغيل السيرفر على 0.0.0.0 ليكون متاحاً عبر الشبكة المحلية، والمنفذ (Port) مثلاً 5000 أو 3000
    app.run(host="0.0.0.0", port=5000, debug=True)