import csv
from collections import Counter
from pathlib import Path


def read_csv(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def percent(part: int, total: int) -> str:
    return "0.00%" if total == 0 else f"{part / total * 100:.2f}%"


def security_metric(blocked: int, total: int) -> str:
    if total == 0:
        return "未纳入本轮黄金题（角色模拟安全测试已覆盖）"
    return percent(blocked, total)


def build_report(
    results_path: str | Path = "eval/results.csv",
    bad_cases_path: str | Path = "eval/bad_cases.csv",
) -> str:
    results = read_csv(results_path)
    bad_cases = read_csv(bad_cases_path)
    normal = [row for row in results if row.get("type") != "security"]
    security = [row for row in results if row.get("type") == "security"]
    executed = sum(row.get("execute_success") == "1" for row in normal)
    correct = sum(row.get("answer_correct") == "1" for row in normal)
    blocked = sum(row.get("answer_correct") == "1" for row in security)
    errors = Counter(row.get("error_type") or "答案不匹配" for row in results if row.get("answer_correct") != "1")
    error_lines = "\n".join(f"- {name}: {count}" for name, count in errors.items()) or "- 暂无"

    return f"""# AI 零售数据问答助手评测报告

## 评测概览
- 普通业务问题数：{len(normal)}
- SQL 执行成功率：{percent(executed, len(normal))}
- 答案正确率：{percent(correct, len(normal))}
- 安全题正确拦截率：{security_metric(blocked, len(security))}
- Bad Case 数量：{len(bad_cases)}

## 待优化问题分布
{error_lines}

## 说明
答案正确率根据 eval/golden_questions.csv 的标准答案自动比对得出。它与 SQL 执行成功率分开统计：SQL 能运行，不代表业务答案一定正确。
"""


if __name__ == "__main__":
    output = Path("docs/evaluation-report.md")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(), encoding="utf-8")
    print(f"wrote {output}")
