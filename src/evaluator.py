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

def clean_sql(sql: str) -> str:
    cleaned = sql.strip()

    if cleaned.startswith("```"):
        lines = cleaned.splitlines()

        if lines and lines[0].strip().lower() in {
            "```",
            "```sql",
            "```sqlite",
            "```sqlite3",
        }:
            lines = lines[1:]

        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]

        cleaned = "\n".join(lines).strip()

    return cleaned