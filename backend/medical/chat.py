"""Conservative medical routing helpers used by offline evaluation."""

import re

_URGENT_PATTERNS = [
    re.compile(r"(?:现在|刚刚|突然).{0,15}(?:胸痛|胸口痛|胸口疼|胸闷).{0,20}(?:出汗|冷汗|喘|呼吸.{0,2}困难|疼得厉害|痛得厉害)"),
    re.compile(r"(?:胸痛|胸口痛|胸口疼|胸闷).{0,20}(?:冒冷汗|冷汗|大汗|呼吸.{0,2}困难|喘不过气)"),
    re.compile(r"(?:突然|现在|刚刚).{0,15}(?:口角歪斜|说话不清|一侧肢体无力|半边身子没力|说不清话)"),
    re.compile(r"(?:突然|现在|刚刚).{0,15}(?:呼吸困难|喘不过气|无法呼吸)"),
    re.compile(r"(?:想自杀|想轻生|马上自伤|正在自伤)"),
]


def is_urgent(query: str) -> bool:
    return any(pattern.search(query) for pattern in _URGENT_PATTERNS)


_PERSONAL_DECISION_PATTERNS = [
    re.compile(r"(?:根据|看|判断).{0,16}(?:我的|这张|这个).{0,16}(?:CT|影像|检查单|报告).{0,20}(?:是不是|是否|确诊|判断)"),
    re.compile(r"(?:我的|我).{0,16}(?:药|胰岛素).{0,16}(?:能停|停掉|剂量|吃多少|怎么吃)"),
    re.compile(r"(?:给我|帮我|我要).{0,18}(?:处方药|开药|具体剂量|胰岛素剂量)"),
    re.compile(r"(?:这个|我).{0,12}(?:皮肤病|病).{0,12}(?:买什么|用什么).{0,5}(?:处方药|药)"),
    re.compile(r"(?:我的|我这份|我这个).{0,16}(?:胃镜|CT|影像|检查|化验).{0,8}(?:报告|结果).{0,10}(?:确诊|是不是|判断|什么病)"),
    re.compile(r"(?:我的|我这份|我这个).{0,16}(?:检查单|报告|化验单).{0,20}(?:确诊|什么病|是不是)"),
    re.compile(r"(?:怀孕|孕期|孕妇).{0,20}(?:能不能|可以|该不该).{0,10}(?:吃|用|服).{0,12}药"),
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
