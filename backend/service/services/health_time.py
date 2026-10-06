"""Chinese health event times independent of the LLM and host timezone."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re

CHINA_TZ = timezone(timedelta(hours=8), "Asia/Shanghai")
PARSER_VERSION = "health-time-v2"


class HealthTimeClarification(ValueError):
    def __init__(self, reason, question):
        super().__init__(reason)
        self.reason, self.question = reason, question


@dataclass(frozen=True)
class ResolvedHealthTime:
    observed_at: datetime
    precision: str
    confidence: str
    date_text: str
    parser_version: str = PARSER_VERSION


def china_local_datetime(value=None):
    value = value or datetime.now(CHINA_TZ)
    return value.astimezone(CHINA_TZ).replace(tzinfo=None) if value.tzinfo else value


def _date_from_text(text, reference):
    phrases = re.findall(r"前天|昨天|昨日|昨晚|今天|今日|今早|明天|后天|上上周[一二三四五六日天]|上周(?:星期)?[一二三四五六日天]|\d{4}年\d{1,2}月\d{1,2}[日号]|\d{4}-\d{1,2}-\d{1,2}|(?<!\d)\d{1,2}月\d{1,2}[日号]|(?<!\d)\d{1,2}[日号]", text)
    if len(phrases) > 1:
        raise HealthTimeClarification("multiple_dates", "这条情况发生在哪一天？请将不同日期的情况分别记录。")
    if not phrases:
        if re.search(r"上周|这周|本周|星期|周[一二三四五六日天]|上个月|去年|昨早|前几天", text):
            raise HealthTimeClarification("unsupported_relative_date", "能补充这条情况的具体日期吗？")
        return None
    phrase = phrases[0]
    offsets = {"前天": -2, "昨天": -1, "昨日": -1, "昨晚": -1, "今天": 0, "今日": 0, "今早": 0, "明天": 1, "后天": 2}
    if phrase in offsets:
        return reference.date() + timedelta(days=offsets[phrase])
    week = re.fullmatch(r"上周(?:星期)?([一二三四五六日天])", phrase)
    if week:
        weekday = "一二三四五六日".index(week[1].replace("天", "日"))
        return reference.date() - timedelta(days=reference.weekday()+7-weekday)
    full = re.fullmatch(r"(\d{4})[年-](\d{1,2})[月-](\d{1,2})[日号]?", phrase)
    if full:
        try:
            return datetime(*map(int, full.groups())).date()
        except ValueError:
            raise HealthTimeClarification("invalid_date", "这个日期不存在，请确认年、月、日。") from None
    raise HealthTimeClarification("ambiguous_date", "请补充完整年月日，例如2026年9月20日，避免记到错误月份。")


def _clock_from_text(text):
    text = text.replace("昨晚", "昨天晚上").replace("今早", "今天早上")
    matches = list(re.finditer(r"(?:(上午|下午|晚上|中午|凌晨|早上)\s*)?(\d{1,2})(?:[:：](\d{2})|[点时](?:(\d{1,2})分?)?(半)?)", text))
    if len(matches) > 1:
        raise HealthTimeClarification("multiple_clocks", "这条情况具体发生在什么时刻？")
    if not matches:
        return None
    period, hour, colon_minute, chinese_minute, half = matches[0].groups()
    hour, minute = int(hour), int(colon_minute or chinese_minute or (30 if half else 0))
    if period and hour > 12:
        raise HealthTimeClarification("invalid_clock", "请使用明确的24小时制时刻。")
    if period in {"下午", "晚上", "中午"} and 1 <= hour <= 11:
        hour += 12
    if period == "凌晨" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        raise HealthTimeClarification("invalid_clock", "请确认具体时刻，使用24小时制会更清楚。")
    return hour, minute


def resolve_health_time(value="", date_text="", precision="minute", *, reference=None):
    if precision not in {"minute", "day", "unknown"}:
        raise ValueError("invalid time_precision")
    now = china_local_datetime(reference)
    day = _date_from_text(date_text, now) if date_text else None
    clock = _clock_from_text(date_text)
    if value:
        try:
            parsed = china_local_datetime(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            raise HealthTimeClarification("invalid_timestamp", "请确认记录的日期与时刻。") from None
        if day and day != parsed.date():
            raise HealthTimeClarification("date_conflict", "记录日期与原话的时间不一致，请确认实际发生日期。")
        if clock and (parsed.hour, parsed.minute) != clock:
            raise HealthTimeClarification("clock_conflict", "记录时刻与原话不一致，请确认实际发生时间。")
        resolved_precision = "day" if "T" not in value and " " not in value else precision
        if clock:
            resolved_precision = "minute"
        if resolved_precision == "day":
            parsed = parsed.replace(hour=0, minute=0, second=0, microsecond=0)
        result = ResolvedHealthTime(parsed, resolved_precision,
                                    "inferred_time" if resolved_precision == "unknown" else "explicit", date_text)
    elif day:
        parsed = datetime.combine(day, datetime.min.time())
        if clock:
            parsed = parsed.replace(hour=clock[0], minute=clock[1])
        result = ResolvedHealthTime(parsed, "minute" if clock else "day", "explicit", date_text)
    else:
        if clock:
            raise HealthTimeClarification("missing_date", "这个时刻是哪一天的？")
        result = ResolvedHealthTime(now, "unknown", "inferred_time", date_text)
    if result.observed_at.date() > now.date() or (result.precision == "minute" and result.observed_at > now):
        raise HealthTimeClarification("future_event", "这个时间在未来。你是在补记已经发生的情况，还是描述未来安排？")
    return result
