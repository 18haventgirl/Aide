"""Conservative medical routing helpers used by offline evaluation."""

import re

def is_urgent(query: str) -> bool:
    """Detect a small set of emergency presentations without diagnosing them."""
    text = re.sub(r"\s+", "", query)
    chest = bool(re.search(r"胸痛|胸口.{0,4}(?:痛|疼|压榨|压着)|胸闷", text))
    cardiopulmonary = bool(re.search(r"冷汗|冒汗|大汗|气不够用|喘不过气|呼吸.{0,3}(?:困难|费劲)", text))
    if chest and cardiopulmonary:
        return True

    neuro_signs = sum(bool(re.search(pattern, text)) for pattern in (
        r"脸歪|口角歪斜",
        r"说话.{0,3}(?:不清|含糊)|说不清话|说不出话",
        r"(?:一侧|一边|半边身子|左手|右手|左臂|右臂).{0,6}(?:无力|没力|使不上劲|麻木|麻)",
    ))
    if neuro_signs >= 2:
        return True
    if re.search(r"(?:一侧|一边|半边身子|左手|右手|左臂|右臂).{0,8}(?:无力|没力|使不上劲|麻木|麻|抬不起来)", text):
        return True
    if re.search(r"呼吸.{0,4}(?:越来越费劲|困难)|喘不过气|无法呼吸|一句完整的话都说不出来", text):
        return True
    if re.search(r"想自杀|想轻生|正在自伤|准备.{0,4}(?:伤害自己|自伤|自杀)|马上.{0,4}(?:伤害自己|自伤|自杀)", text):
        return True
    severe_headache = bool(re.search(r"突然.{0,8}(?:最严重|剧烈|炸裂|雷击).{0,5}头痛|这辈子最严重的头痛", text))
    if severe_headache and re.search(r"呕吐|脖子硬|意识|抽搐|说话|无力", text):
        return True
    return False


_PERSONAL_DECISION_PATTERNS = [
    re.compile(r"(?:根据|看|判断).{0,16}(?:我的|这张|这个).{0,16}(?:CT|影像|检查单|报告).{0,20}(?:是不是|是否|确诊|判断)"),
    re.compile(r"(?:我的|我).{0,16}(?:药|胰岛素).{0,16}(?:能停|停掉|剂量|吃多少|怎么吃)"),
    re.compile(r"(?:给我|帮我|我要).{0,18}(?:处方药|开药|具体剂量|胰岛素剂量)"),
    re.compile(r"(?:这个|我).{0,12}(?:皮肤病|病).{0,12}(?:买什么|用什么).{0,5}(?:处方药|药)"),
    re.compile(r"(?:我的|我这份|我这个).{0,16}(?:胃镜|CT|影像|检查|化验).{0,8}(?:报告|结果).{0,10}(?:确诊|是不是|判断|什么病)"),
    re.compile(r"(?:我的|我这份|我这个).{0,16}(?:检查单|报告|化验单).{0,20}(?:确诊|什么病|是不是)"),
    re.compile(r"(?:怀孕|孕期|孕妇).{0,20}(?:能不能|可以|该不该).{0,10}(?:吃|用|服).{0,12}药"),
    re.compile(r"(?:孩子|儿童|宝宝|婴儿|\d+岁).{0,20}(?:吃|用|服).{0,12}(?:几毫升|多少毫升|多少片|剂量|退烧药)"),
    re.compile(r"(?:药|阿莫西林|布洛芬).{0,20}(?:一起吃|同时吃|合用).{0,16}(?:剂量|怎么吃|多少)"),
    re.compile(r"(?:把|将).{0,10}(?:药|降压药|用药).{0,12}(?:改成|调整为|换成).{0,12}(?:一天|每日|每次)"),
    re.compile(r"(?:照片|图片).{0,16}(?:痣|皮疹|肿块).{0,16}(?:恶性|癌|肿瘤|什么病|判断)"),
    re.compile(r"(?:能|可以|能否).{0,10}(?:确定|判断|确诊).{0,16}(?:哪种病|什么病|病因|诊断)"),
]


def needs_clinical_decision(query: str) -> bool:
    """Block requests for a personal diagnosis, prescription, or drug change."""
    return any(pattern.search(query) for pattern in _PERSONAL_DECISION_PATTERNS)


def is_out_of_scope(query: str) -> bool:
    return needs_clinical_decision(query) or bool(re.search(r"(?:我家|我的).{0,4}(?:猫|狗|宠物).{0,16}(?:绝育|看病|吃药|花多少钱)", query))


def contextual_query(question: str, history: list[dict]) -> str:
    """Resolve short follow-ups with one prior user turn before local retrieval."""
    current = question.strip()
    if len(current) > 30 or not re.search(r"^(?:那|那么|这种|这个|刚才|上面|它|还|如果)", current):
        return current
    previous = next((item.get("content", "") for item in reversed(history)
                     if item.get("role") == "user" and isinstance(item.get("content"), str)), "")
    previous = previous.strip()[-200:]
    return f"{previous}\n追问：{current}" if previous else current


def contextual_facts_query(question: str, prior_user_facts: str = "") -> str:
    """Combine an explicit follow-up with bounded facts stated by the user."""
    current = " ".join(question.strip().split())
    facts = " ".join(prior_user_facts.strip().split())[-500:]
    if not facts:
        return current
    return f"用户此前明确陈述：{facts}\n当前问题：{current}"
