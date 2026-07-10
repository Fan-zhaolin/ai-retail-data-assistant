import argparse
import csv
from pathlib import Path
from typing import Callable

from src.db import run_sql as default_run_sql
from src.evaluator import is_safe_sql
from src.llm import ask_llm as default_ask_llm
from src.prompts import build_sql_prompt as default_build_prompt


RESULT_FIELDS = [
    "id",
    "question",
    "generated_sql",
    "execute_success",
    "answer_correct",
    "error_type",
    "note",
]

BAD_CASE_FIELDS = [
    "case_id",
    "question",
    "wrong_sql",
    "error_type",
    "reason",
    "fix_plan",
]


def clean_sql(raw_sql: str) -> str:
    sql = raw_sql.strip()
    if sql.startswith("```"):
        lines = sql.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        sql = "\n".join(lines).strip()
    return sql.rstrip(";") + ";"


def _read_questions(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def evaluate_questions(
    questions_path: str | Path = "eval/questions.csv",
    results_path: str | Path = "eval/results.csv",
    bad_cases_path: str | Path = "eval/bad_cases.csv",
    ask_llm: Callable[[str], str] = default_ask_llm,
    run_sql: Callable[[str], object] = default_run_sql,
    build_prompt: Callable[[str], str] = default_build_prompt,
    limit: int | None = None,
    verbose: bool = True,
) -> None:
    questions = _read_questions(Path(questions_path))
    if limit is not None:
        questions = questions[:limit]
    result_rows: list[dict[str, str]] = []
    bad_case_rows: list[dict[str, str]] = []

    for question in questions:
        qid = question.get("id", "")
        qtext = question.get("question", "")
        qtype = question.get("type", "")

        try:
            generated_sql = clean_sql(ask_llm(build_prompt(qtext)))
        except Exception as exc:
            generated_sql = ""
            result_rows.append(
                {
                    "id": qid,
                    "question": qtext,
                    "generated_sql": generated_sql,
                    "execute_success": "0",
                    "answer_correct": "0",
                    "error_type": "llm_error",
                    "note": str(exc),
                }
            )
            bad_case_rows.append(
                {
                    "case_id": str(len(bad_case_rows) + 1),
                    "question": qtext,
                    "wrong_sql": generated_sql,
                    "error_type": "llm_error",
                    "reason": str(exc),
                    "fix_plan": "检查 .env、模型名、API 地址和网络连接。",
                }
            )
            continue

        if not is_safe_sql(generated_sql):
            is_expected_security_case = qtype == "security"
            result_rows.append(
                {
                    "id": qid,
                    "question": qtext,
                    "generated_sql": generated_sql,
                    "execute_success": "0",
                    "answer_correct": "1" if is_expected_security_case else "0",
                    "error_type": "security",
                    "note": "安全校验拦截，未执行 SQL。",
                }
            )
            bad_case_rows.append(
                {
                    "case_id": str(len(bad_case_rows) + 1),
                    "question": qtext,
                    "wrong_sql": generated_sql,
                    "error_type": "security",
                    "reason": "SQL 未通过只读安全校验。",
                    "fix_plan": "保持拦截；若这是普通题，需优化 Prompt，强调只能输出 SELECT。",
                }
            )
            continue

        try:
            result = run_sql(generated_sql)
            row_count = len(result) if hasattr(result, "__len__") else "unknown"
            result_rows.append(
                {
                    "id": qid,
                    "question": qtext,
                    "generated_sql": generated_sql,
                    "execute_success": "1",
                    "answer_correct": "",
                    "error_type": "",
                    "note": f"执行成功，返回 {row_count} 行；答案正确性需人工复核。",
                }
            )
        except Exception as exc:
            result_rows.append(
                {
                    "id": qid,
                    "question": qtext,
                    "generated_sql": generated_sql,
                    "execute_success": "0",
                    "answer_correct": "0",
                    "error_type": "execute_error",
                    "note": str(exc),
                }
            )
            bad_case_rows.append(
                {
                    "case_id": str(len(bad_case_rows) + 1),
                    "question": qtext,
                    "wrong_sql": generated_sql,
                    "error_type": "execute_error",
                    "reason": str(exc),
                    "fix_plan": "检查字段名、表名、JOIN 条件和 SQLite 语法。",
                }
            )

    _write_csv(Path(results_path), RESULT_FIELDS, result_rows)
    _write_csv(Path(bad_cases_path), BAD_CASE_FIELDS, bad_case_rows)
    if verbose:
        print(f"wrote {results_path}")
        print(f"wrote {bad_cases_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Evaluate Text-to-SQL questions.")
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Only evaluate the first N questions, useful for a small API test.",
    )
    args = parser.parse_args()
    evaluate_questions(limit=args.limit)
