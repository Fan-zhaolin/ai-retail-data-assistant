import argparse
import csv
from collections import Counter
from pathlib import Path


def _read_csv(path: str | Path) -> list[dict[str, str]]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _percent(part: int, total: int) -> str:
    if total == 0:
        return "0.00%"
    return f"{part / total * 100:.2f}%"


def _counter_lines(counter: Counter[str]) -> str:
    if not counter:
        return "- 暂无"
    return "\n".join(f"- {key or '未分类'}：{value}" for key, value in counter.items())


def build_report(
    results_path: str | Path = "eval/results.csv",
    bad_cases_path: str | Path = "eval/bad_cases.csv",
) -> str:
    results = _read_csv(results_path)
    bad_cases = _read_csv(bad_cases_path)

    total = len(results)
    execute_success = sum(1 for row in results if row.get("execute_success") == "1")
    answer_correct = sum(1 for row in results if row.get("answer_correct") == "1")
    security_blocks = sum(1 for row in results if row.get("error_type") == "security")
    result_error_types = Counter(row.get("error_type", "") for row in results if row.get("error_type", ""))
    bad_case_types = Counter(row.get("error_type", "") for row in bad_cases if row.get("error_type", ""))

    return f"""# AI 零售数据问答助手评测报告

## 评测概览
- 评测问题数：{total}
- SQL 执行成功数：{execute_success}
- SQL 执行成功率：{_percent(execute_success, total)}
- 已确认正确数：{answer_correct}
- 安全拦截数：{security_blocks}
- Bad Case 数量：{len(bad_cases)}

## 错误类型分布
{_counter_lines(result_error_types)}

## Bad Case 类型分布
{_counter_lines(bad_case_types)}

## 典型 Bad Case
{_format_bad_cases(bad_cases)}

## 结论
本项目已经形成自然语言问题、SQL 生成、安全校验、数据库查询、结果展示、业务解释和评测复盘的闭环。

## 下一步优化
- 扩展评测集到 40 条以上，覆盖更多指标口径、时间趋势和组合筛选问题。
- 持续复核 answer_correct 字段，将人工确认结果沉淀为稳定评测证据。
- 针对 Bad Case 优化 Prompt、指标口径说明和 SQL 安全规则。
"""


def _format_bad_cases(rows: list[dict[str, str]]) -> str:
    if not rows:
        return "- 暂无 Bad Case。"
    lines = []
    for row in rows[:5]:
        lines.append(
            f"- {row.get('question', '')}：{row.get('error_type', '')}；"
            f"原因：{row.get('reason', '')}；优化：{row.get('fix_plan', '')}"
        )
    return "\n".join(lines)


def write_report(
    output_path: str | Path = "docs/evaluation-report.md",
    results_path: str | Path = "eval/results.csv",
    bad_cases_path: str | Path = "eval/bad_cases.csv",
) -> Path:
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(build_report(results_path, bad_cases_path), encoding="utf-8")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build evaluation report markdown.")
    parser.add_argument("--output", default="docs/evaluation-report.md")
    args = parser.parse_args()
    path = write_report(args.output)
    print(f"wrote {path}")
