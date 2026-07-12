import argparse
import csv
import math
import re

from pathlib import Path
from typing import Callable
from src.db import run_sql as default_run_sql
from src.evaluator import clean_sql, is_safe_sql
from src.llm import ask_llm as default_ask_llm
from src.prompts import build_sql_prompt as default_build_prompt

RESULT_FIELDS = [
    "id", "type", "question", "generated_sql", "execute_success",
    "expected_value", "answer_correct", "difference", "error_type",
     "note", "prompt_version",
]
BAD_CASE_FIELDS = [
 "case_id", "question", "wrong_sql", "error_type", "reason", "fix_plan",
]
def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))
    
def write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
         writer = csv.DictWriter(file, fieldnames=fields)
         writer.writeheader()
         writer.writerows(rows)

def as_number(value: object) -> float | None:
     text = str(value).strip().replace(",", "")
     if text.lower() in {"", "none", "nan", "null"}:
        return None
     try:
        return float(text)
     except ValueError:
        return None
     
def numbers_match(actual: float, expected: float, tolerance: float) -> bool:
    if math.isclose(actual, expected, abs_tol=tolerance):
        return True
    if 0 < abs(expected) < 1:
        return math.isclose(actual, expected * 100, abs_tol=tolerance * 100)
    return False

def check_answer(result: object, golden: dict[str, str]) -> tuple[bool, str]:
    expected = golden.get("expected_value", "").strip()
    tolerance = float(golden.get("tolerance") or 0.01)
    question_type = golden.get("type", "")

    if question_type == "empty":
        if len(result) == 0:
            return True, "返回 0 行，符合预期。"
        visible_values = [value for value in result.to_numpy().flatten() if as_number(value) is not None]
        if visible_values and all(as_number(value) == 0 for value in visible_values):
            return True, "结果值均为 0，符合预期。"
        return False, "预期为空或 0，但实际返回了非零结果。"
   
    actual_values = list(result.to_numpy().flatten())
    missing = []
    for token in re.split(r"[|;]", expected):
        token = token.strip()
        if not token:
            continue
        expected_number = as_number(token)
        if expected_number is not None:
            matched = any(
                actual_number is not None and numbers_match(actual_number, expected_number, tolerance)
                for actual_number in (as_number(value) for value in actual_values)
            )
        else:
            matched = any(token.lower() in str(value).lower() for value in actual_values)
        if not matched:
            missing.append(token)

    if missing:
        return False, "未匹配标准值：" + "、".join(missing)
    return True, "关键结果与黄金答案匹配。"

def evaluate_questions(
    questions_path: str | Path = "eval/golden_questions.csv",
    results_path: str | Path = "eval/results.csv",
    bad_cases_path: str | Path = "eval/bad_cases.csv",
    ask_llm: Callable[[str], str] = default_ask_llm,
    run_sql: Callable[[str], object] = default_run_sql,
    build_prompt: Callable[[str], str] = default_build_prompt,
    limit: int | None = None,
    ids: set[str] | None = None,
    verbose: bool = True,
) -> None:
    questions = read_csv(Path(questions_path))
    if ids:
        questions = [question for question in questions if question.get("id") in ids]
    if limit is not None:
        questions = questions[:limit]

    result_rows: list[dict[str, str]] = []
    bad_case_rows: list[dict[str, str]] = []

    for golden in questions:
        qid = golden.get("id", "")
        question = golden.get("question", "")
        question_type = golden.get("type", "")
        expected_value = golden.get("expected_value", "")
        expected_block = golden.get("expected_block", "false").lower() == "true"
        base_row = {
            "id": qid,
            "type": question_type,
            "question": question,
            "expected_value": expected_value,
            "prompt_version": "v2.0",
        }

        try:
            generated_sql = clean_sql(ask_llm(build_prompt(question)))
        except Exception as exc:
            result_rows.append({**base_row, "generated_sql": "", "execute_success": "0", "answer_correct": "0", 
"difference": "模型调用失败", "error_type": "llm_error", "note": str(exc)})
            continue

        if not is_safe_sql(generated_sql):
            is_correct = expected_block
            result_rows.append({**base_row, "generated_sql": generated_sql, "execute_success": "0", 
"answer_correct": "1" if is_correct else "0", "difference": "安全拦截", "error_type": "security", "note": "SQL"
"未执行。"})
            bad_case_rows.append({
                "case_id": str(len(bad_case_rows) + 1),
                "question": question,
                "wrong_sql": generated_sql,
                "error_type": "security",
                "reason": "SQL 未通过只读安全校验，未执行。",
                "fix_plan": "保留 SQL 安全校验，并为危险请求补充回归用例。",
            })
            continue
        
        try:
            result = run_sql(generated_sql)
            is_correct, difference = check_answer(result, golden)
            result_rows.append({**base_row, "generated_sql": generated_sql, "execute_success": "1", 
"answer_correct": "1" if is_correct else "0", "difference": difference, "error_type": "", "note": f"执行成功，返回 {len(result)} 行。"})
            if not is_correct:
                bad_case_rows.append({"case_id": str(len(bad_case_rows) + 1), "question": question, "wrong_sql": 
generated_sql, "error_type": "answer_mismatch", "reason": difference, "fix_plan": "检查数据字典、中文枚举映射和Prompt 中的指标口径。"})
        except Exception as exc:
            result_rows.append({**base_row, "generated_sql": generated_sql, "execute_success": "0", 
"answer_correct": "0", "difference": "SQL 执行报错", "error_type": "execute_error", "note": str(exc)})
            bad_case_rows.append({"case_id": str(len(bad_case_rows) + 1), "question": question, "wrong_sql": 
generated_sql, "error_type": "execute_error", "reason": str(exc), "fix_plan": "检查字段名、表名、JOIN 条件和SQLite 语法。"})
    write_csv(Path(results_path), RESULT_FIELDS, result_rows)
    write_csv(Path(bad_cases_path), BAD_CASE_FIELDS, bad_case_rows)
    if verbose:
        print(f"wrote {results_path}")
        print(f"wrote {bad_cases_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--ids", default="", help="Comma-separated question IDs, for example G03,G07")
    parser.add_argument("--results-path", default="eval/results.csv")
    parser.add_argument("--bad-cases-path", default="eval/bad_cases.csv")
    args = parser.parse_args()
    selected_ids = {value.strip() for value in args.ids.split(",") if value.strip()}
    evaluate_questions(
        limit=args.limit,
        ids=selected_ids or None,
        results_path=args.results_path,
        bad_cases_path=args.bad_cases_path,
    )
