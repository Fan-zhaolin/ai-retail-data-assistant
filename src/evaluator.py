import re


FORBIDDEN = ["drop", "delete", "update", "insert", "alter", "truncate", "create", "replace"]
RISKY_INTENT_WORDS = [
    "drop",
    "delete",
    "update",
    "insert",
    "alter",
    "truncate",
    "create",
    "replace",
    "删除",
    "清空",
    "修改",
    "改成",
    "插入",
    "建表",
    "删表",
]


def _strip_trailing_semicolon(sql: str) -> str:
    return sql.strip().rstrip(";").strip()


def is_safe_sql(sql: str) -> bool:
    normalized = _strip_trailing_semicolon(sql)
    lowered = normalized.lower()

    if not (lowered.startswith("select") or lowered.startswith("with")):
        return False

    if ";" in normalized:
        return False

    return not any(re.search(rf"\b{word}\b", lowered) for word in FORBIDDEN)


def has_risky_intent(question: str) -> bool:
    lowered = question.lower()
    return any(word in lowered for word in RISKY_INTENT_WORDS)
