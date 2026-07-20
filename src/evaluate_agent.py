from __future__ import annotations

import argparse
from pathlib import Path
import tempfile

import pandas as pd

from src.db import DB_PATH, ensure_database
from src.ops_agent import run_ops_agent


TASK_FILE = Path("eval/agent_tasks.csv")
RESULT_FILE = Path("eval/agent_results.csv")
REPORT_FILE = Path("docs/agent-evaluation-report.md")


def evaluate_agent_tasks(
    task_file: str | Path = TASK_FILE,
    db_path: str | Path = DB_PATH,
) -> pd.DataFrame:
    tasks = pd.read_csv(task_file)
    required = {"id", "query", "expected_route", "expected_status"}
    missing = required - set(tasks.columns)
    if missing:
        raise ValueError(f"Agent 评测集缺少字段：{', '.join(sorted(missing))}")

    ensure_database()
    rows: list[dict[str, object]] = []
    with tempfile.TemporaryDirectory(prefix="agent-eval-") as tmp:
        action_db = Path(tmp) / "agent_actions.db"
        for item in tasks.to_dict(orient="records"):
            result = run_ops_agent(
                str(item["query"]),
                db_path=db_path,
                action_db_path=action_db,
                session_id="offline-evaluation",
            )
            trace = result.get("trace") or []
            actual_status = trace[-1]["status"] if trace else "no_trace"
            route_pass = result.get("route") == item["expected_route"]
            status_pass = actual_status == item["expected_status"]
            rows.append(
                {
                    **item,
                    "actual_route": result.get("route"),
                    "actual_status": actual_status,
                    "route_pass": route_pass,
                    "status_pass": status_pass,
                    "passed": route_pass and status_pass,
                    "tool_count": len(trace),
                    "requires_approval": bool(result.get("requires_approval")),
                    "response": result.get("response", ""),
                }
            )
    return pd.DataFrame(rows)


def build_report(results: pd.DataFrame) -> str:
    total = len(results)
    passed = int(results["passed"].sum()) if total else 0
    route_passed = int(results["route_pass"].sum()) if total else 0
    status_passed = int(results["status_pass"].sum()) if total else 0
    approval_cases = int(results["requires_approval"].sum()) if total else 0
    failed = results[~results["passed"]]

    lines = [
        "# 零售运营 Agent 离线评测报告",
        "",
        "本报告只针对固定的演示任务集，不代表开放式真实用户请求的准确率。",
        "订单状态、库存和政策均为基于公开销售数据生成的合成演示数据。",
        "",
        "## 结果摘要",
        "",
        f"- 任务数：{total}",
        f"- 完整通过：{passed}/{total}（{passed / total:.2%}）" if total else "- 完整通过：0/0",
        f"- 路由正确：{route_passed}/{total}",
        f"- 最终状态正确：{status_passed}/{total}",
        f"- 触发人工审批的任务：{approval_cases}",
        "",
        "## 覆盖范围",
        "",
        "- 订单查询：存在订单与不存在订单",
        "- 库存查询：正常库存、低库存、未知商品和缺少商品编号",
        "- 退货政策：多个品类与未指定品类",
        "- 退货申请：窗口内、超期、未送达、未知订单和缺少订单号",
        "- 安全控制：写操作在人工批准前停留在 waiting_approval",
        "- 异常输入：无法路由的宽泛任务要求澄清",
        "",
        "## 失败任务",
        "",
    ]
    if failed.empty:
        lines.append("当前固定评测集没有失败任务。后续仍需用真实开放式表达补充 Bad Case。")
    else:
        lines.append(failed[["id", "query", "expected_route", "actual_route", "expected_status", "actual_status"]].to_markdown(index=False))
    lines.extend(
        [
            "",
            "## 边界",
            "",
            "- 评测使用确定性路由和固定工具，不调用外部大模型。",
            "- 创建退货申请仅写入本地演示库，不调用真实退款或订单系统。",
            "- 固定任务通过不能证明真实客服场景中的语言理解、政策完整性或业务收益。",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate the controlled retail operations agent")
    parser.add_argument("--tasks", default=str(TASK_FILE))
    parser.add_argument("--output", default=str(RESULT_FILE))
    parser.add_argument("--report", default=str(REPORT_FILE))
    args = parser.parse_args()

    results = evaluate_agent_tasks(args.tasks)
    output = Path(args.output)
    report = Path(args.report)
    output.parent.mkdir(parents=True, exist_ok=True)
    report.parent.mkdir(parents=True, exist_ok=True)
    results.to_csv(output, index=False, encoding="utf-8-sig")
    report.write_text(build_report(results), encoding="utf-8")
    print(f"agent tasks: {len(results)}")
    print(f"passed: {int(results['passed'].sum())}")
    print(f"results: {output}")
    print(f"report: {report}")


if __name__ == "__main__":
    main()
