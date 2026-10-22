"""Auditable, local estimates from stated activity; never uses an LLM PAL guess."""
import math
import re

VERSION = "2026-10-11-met-v1"
SOURCES = [
    {"title": "静息能量：Mifflin–St Jeor 原始研究", "url": "https://pubmed.ncbi.nlm.nih.gov/2305711/"},
    {"title": "日常活动背景：NIDDK", "url": "https://www.niddk.nih.gov/bwp"},
    {"title": "力量训练：2024 活动代谢当量表", "url": "https://pacompendium.com/conditioning-exercise/"},
    {"title": "游泳：2024 活动代谢当量表", "url": "https://pacompendium.com/water-activities/"},
    {"title": "蛋白质：ISSN 运动营养立场声明", "url": "https://pmc.ncbi.nlm.nih.gov/articles/PMC5477153/"},
    {"title": "成人营养素供能参考", "url": "https://www.canada.ca/en/health-canada/services/food-nutrition/healthy-eating/dietary-reference-intakes/tables/reference-values-macronutrients.html"},
]


def goal_direction(text):
    """Recognize explicit common goals; ambiguity/negation never defaults to maintenance."""
    text = str(text).strip()
    if re.search(r"不|无需|无须|避免|先.*再|以后|将来", text):
        return None
    loss = bool(re.search(r"减脂|减重|减肥|降体脂|降低体脂|腹肌.{0,4}(清晰|明显)|清晰.{0,4}腹肌", text))
    gain = bool(re.search(r"增重|增肌|增大肌肉", text))
    keep = bool(re.search(r"维持体重|保持体重|^维持$|^保持现状$", text))
    if sum((loss, gain, keep)) != 1:
        return None
    return "减脂" if loss else "增肌" if gain else "保持现状"


def normalized(text):
    digits = dict(zip("零一二三四五六七八九", "0123456789"))

    def number(match):
        token = match[0].replace("两", "二")
        if "十" in token:
            left, right = token.split("十")
            return str(int(digits.get(left, "1")) * 10 + int(digits.get(right, "0")))
        return "".join(digits.get(c, c) for c in token)

    text = re.sub(r"[零一二两三四五六七八九十]+", number, str(text))
    text = re.sub(r"(\d+)个半小时", lambda m: str(float(m[1]) + .5) + "小时", text)
    text = re.sub(r"(\d+)小时半", lambda m: str(float(m[1]) + .5) + "小时", text)
    return text.replace("半小时", "0.5小时").replace("个小时", "小时")


def activity_breakdown(description, weight):
    """Use counts/minutes; optional activity details refine explicit starting assumptions."""
    text = normalized(description)
    missing, assumptions, groups = [], [], []
    active_background = bool(re.search(r"不.{0,3}久坐|经常走动|站立工作", text))
    baseline_factor = 1.6 if active_background else 1.4
    if re.search(r"重体力|体力劳动", text):
        missing.append("体力劳动超出普通日常活动起始估算范围")
    assumptions.append(f"非训练日常背景暂按静息消耗×{baseline_factor:g}估计；" + ("根据经常走动的描述选取。" if active_background else "未细分时以久坐为起点。") + "这不是实测全天消耗，不包含下列专项训练。")
    for clause in re.split(r"[，,；;。\n]+", text):
        clause = clause.strip()
        if not clause:
            continue
        kind = "strength" if re.search(r"力量|抗阻|举铁|器械训练", clause) else "cardio" if re.search(r"有氧|游泳|蛙泳|自由泳|仰泳|蝶泳|跑步|骑行|骑车|快走", clause) else None
        if kind:
            if groups and groups[-1]["kind"] == kind and not re.search(r"[0-9]+\s*(?:次|天)", clause):
                groups[-1]["text"] += "，" + clause
            else:
                groups.append({"kind": kind, "text": clause})
        elif re.search(r"HIIT|瑜伽|球|爬|登山|跳绳|其他运动", clause, re.I):
            missing.append("尚未支持自动换算的活动：" + clause)
        elif re.search(r"休息|久坐|坐班|走动|工作|上班|不运动|无运动", clause):
            continue
        elif groups and re.search(r"每次|各|分钟|小时|min|\d+\s*m\b|\d+米", clause, re.I):
            groups[-1]["text"] += "，" + clause
        elif re.search(r"训练|运动|健身|\d+\s*(?:次|天)", clause):
            missing.append("尚未明确类型或时长的活动：" + clause)
    if not groups and not re.search(r"不运动|无运动|没有.{0,3}(训练|运动)|无专项训练", text):
        missing.append("每周各项训练的次数与每次时长，或明确没有专项训练")
    items = []
    for group in groups:
        raw, kind = group["text"], group["kind"]
        name = "力量训练" if kind == "strength" else "游泳" if re.search(r"游泳|蛙泳|自由泳|仰泳|蝶泳", raw) else "有氧"
        counts = re.findall(r"(\d+(?:\.\d+)?)\s*(?:次|天)", raw)
        if re.search(r"每天|每日", raw):
            counts.append("7")
        durations = re.findall(r"(\d+(?:\.\d+)?)\s*(分钟|小时|minutes?|mins?)", raw, re.I)
        if len(counts) != 1 or len(durations) != 1:
            missing.append(name + "需要唯一的每周次数与每次分钟数；距离不能替代时长")
            continue
        count = float(counts[0])
        minutes = float(durations[0][0]) * (60 if durations[0][1] == "小时" else 1)
        if not (0 < count <= 14 and count.is_integer() and 0 < minutes <= 240):
            missing.append(name + "次数或时长需核对")
            continue
        if re.search(r"不做|没有|暂停|不游|无力量", raw):
            missing.append(name + "描述包含否定，请核对当前实际安排")
            continue
        if kind == "strength":
            met, code = 3.5, "02054"
            assumption = "一般多动作抗阻训练暂取3.5 MET；总时长含组间休息，不按全程高强度举重计算，实际强度及休息会造成误差。"
        elif "蛙泳" in raw and not re.search(r"自由泳|仰泳|蝶泳", raw):
            met, code = (10.3, "18260") if re.search(r"高强度|比赛", raw) else (5.3, "18265")
            assumption = "蛙泳按" + ("训练/竞赛" if met == 10.3 else "休闲强度") + "代谢当量估计；游泳分钟数应为实际游动时间。"
        elif "自由泳" in raw and not re.search(r"仰泳|蝶泳", raw):
            met, code = (9.8, "18230") if re.search(r"高强度|快速|比赛", raw) else (5.8, "18240")
            assumption = "自由泳按" + ("快速" if met == 9.8 else "慢速休闲") + "代谢当量估计；游泳分钟数应为实际游动时间。"
        else:
            met, code = 5, None
            assumption = "有氧未细分时以中等强度5 MET作为软件起始假设，不冒充具体运动的实测值；次数和时长按原文计算。"
        weekly = (met - 1) * weight * minutes / 60 * count
        items.append({"name": name, "description": raw, "sessions_per_week": int(count), "minutes_per_session": minutes,
                      "met": met, "compendium_code": code, "weekly_net_kcal": round(weekly, 2),
                      "daily_net_kcal": round(weekly / 7, 2), "assumption": assumption})
    if sum(i["sessions_per_week"] * i["minutes_per_session"] for i in items) > 1680:
        missing.append("每周训练超过28小时，超出当前一般活动估算范围")
    return {"description": str(description), "baseline_factor": baseline_factor,
            "items": items, "missing": list(dict.fromkeys(missing)), "assumptions": assumptions}


def estimate(values):
    result = {"version": VERSION, "status": "needs_info", "kcal": None, "daily": None,
              "sources": [s["url"] for s in SOURCES], "source_details": SOURCES, "steps": []}
    try:
        age, height, weight = (float(values[k]) for k in ("年龄", "身高", "体重"))
        sex = values["生理性别"]
    except (KeyError, ValueError, TypeError):
        return {**result, "note": "补充年龄、身高、体重与生理性别后计算起始参考。"}
    if not all(math.isfinite(v) for v in (age, height, weight)) or height <= 0 or not 19 <= age <= 64 or sex not in ("男", "女") or not 18.5 <= weight / (height / 100) ** 2 < 40 or values.get("特殊健康情况", "无") not in ("", "无"):
        return {**result, "status": "not_applicable", "note": "当前情况不适用本平台一般成人活动估算，可依据专业评估设定目标。"}
    resting = 10 * weight + 6.25 * height - 5 * age + (5 if sex == "男" else -161)
    result["steps"].append({"label": "静息消耗估算", "formula": f"10×{weight:g} + 6.25×{height:g} − 5×{age:g} {'+ 5' if sex == '男' else '− 161'}", "value": round(resting, 2), "unit": "大卡/天"})
    goal = goal_direction(values.get("目标", ""))
    result["goal"] = {"description": str(values.get("目标", "")), "direction": goal}
    activity = activity_breakdown(values.get("活动量", ""), weight)
    result["activity"] = activity
    missing = list(activity["missing"])
    if not goal:
        missing.insert(0, "明确的目标方向：增肌、减脂或保持现状；含糊或相互冲突的目标不默认按维持处理")
    if missing:
        return {**result, "note": "参考量待核对：" + "；".join(missing) + "。"}
    baseline = resting * activity["baseline_factor"]
    extra = sum((i["met"] - 1) * weight * i["minutes_per_session"] / 60 * i["sessions_per_week"] / 7 for i in activity["items"])
    maintenance = baseline + extra
    # Explicit product planning choices, not a guideline-mandated individualized prescription.
    factor = {"减脂": .85, "保持现状": 1, "增肌": 1.05}[goal]
    amount = round(maintenance * factor / 50) * 50
    training = bool(activity["items"])
    protein = round(weight * (2 if goal == "减脂" else 1.6)) if training else round(amount * .2 / 4)
    fat = round(amount * (.25 if goal == "减脂" else .3) / 9)
    carbs = round((amount - 4 * protein - 9 * fat) / 4)
    if amount < resting or carbs < 130 or protein * 4 > amount * .35:
        return {**result, "status": "needs_review", "note": "起始分配超出当前估算的适用边界，需要个别评估；未自动压低其他营养素。"}
    result["steps"].extend([
        {"label": "非训练日常背景", "formula": f"{resting:g} × {activity['baseline_factor']:g}（日常背景假设）", "value": round(baseline, 2), "unit": "大卡/天"},
        *[{"label": i["name"] + "净增消耗", "formula": f"({i['met']:g} − 1) × {weight:g} × {i['minutes_per_session']:g}/60 × {i['sessions_per_week']}/7", "value": i["daily_net_kcal"], "unit": "大卡/天"} for i in activity["items"]],
        {"label": "维持热量估算", "formula": f"{baseline:.2f} + {extra:.2f}", "value": round(maintenance, 2), "unit": "大卡/天"},
        {"label": "起始摄入参考", "formula": f"{maintenance:.2f} × {factor:g}，取整至50大卡", "value": amount, "unit": "大卡/天"},
        {"label": "蛋白质", "formula": f"{weight:g} × {2 if goal == '减脂' else 1.6} 克/公斤体重" if training else f"{amount} × 20% ÷ 4", "value": protein, "unit": "克/天"},
        {"label": "脂肪", "formula": f"{amount} × {25 if goal == '减脂' else 30}% ÷ 9", "value": fat, "unit": "克/天"},
        {"label": "碳水", "formula": f"({amount} − {protein}×4 − {fat}×9) ÷ 4", "value": carbs, "unit": "克/天"},
    ])
    return {**result, "status": "estimated", "kcal": {"low": amount, "high": amount},
            "daily": {"kcal": amount, "protein_g": protein, "fat_g": fat, "carbs_g": carbs},
            "scoring_context": {"version": "adult-reference-context-v1", "applicable": True,
                                "weight_kg": weight, "training": training, "goal": goal,
                                "note": "此参考生成时的成人适用性与运动背景快照；不回填旧日期。"},
            "note": "起始估算，尚未用体重趋势校准；请结合后续一至两周的完整饮食记录、体重趋势与训练表现复核。",
            "activity_basis": "训练按每周次数×每次分钟数逐项估算，周总量除以7；MET减1扣除同一时段的静息能量，避免直接重复加上训练总消耗。",
            "method": "Mifflin–St Jeor静息估算＋日常背景＋训练净增消耗。减脂保肌暂取15%能量缺口、运动者蛋白质2克/公斤、脂肪25%供能，碳水补齐剩余能量；维持/增肌分别×1/1.05，运动者蛋白质1.6克/公斤、脂肪30%。这些单值是透明的产品起始假设，不是指南给个人的精确处方，也未使用NIDDK动态体重模型。"}
