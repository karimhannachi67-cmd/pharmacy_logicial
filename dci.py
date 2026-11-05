"""مجموعات الـ DCI: داخلية في السيرفر برك، ما تبانش في الواجهة.

كل DCI عندو اسم ومجموعة أدوية تحتو.
القاعدة: المريض ما يقدرش يشري أكثر من دواء من نفس الـ DCI قبل ما تنتهي المدة،
وبدواء من DCI آخر يقدر في أي وقت.

باش تزيد دواء:    زيدو في قائمة DCI موجود، أو في DCI جديد.
باش تزيد DCI جديد: زيد سطر جديد "اسم_الـDCI": ["دواء1", "دواء2"].
الأسماء ما يهمش كبير/صغير، بصح لازم تكون نفس الكتابة اللي في DRUGS في index.html.
دواء ما كاينش هنا يتعامل كـ DCI لوحدو.
"""
DCI = {
    "rani":  ["Erica", "Pregabalin"],
    "karim": ["Paracetamol"],
}


def norm(name):
    return " ".join(str(name).lower().split())


_DRUG2DCI = {}
for _group, _drugs in DCI.items():
    for _d in _drugs:
        if norm(_d) in _DRUG2DCI:
            print(f"[dci.py] تحذير: الدواء {_d} مكتوب في أكثر من DCI، نستعمل الأول ({_DRUG2DCI[norm(_d)]})")
        else:
            _DRUG2DCI[norm(_d)] = _group


def key(name):
    n = norm(name)
    return _DRUG2DCI.get(n, "n:" + n)
