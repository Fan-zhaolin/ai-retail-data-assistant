from pathlib import Path

import pandas as pd

from src.db import run_sql


RAW_CHANNEL_SQL = """
SELECT
    sales_channel,
    ROUND(SUM(sales_amount), 2) AS net_sales,
    COUNT(DISTINCT transaction_id) AS order_count,
    ROUND(SUM(sales_amount) / COUNT(DISTINCT transaction_id), 2) AS avg_order_value
FROM fact_sales
GROUP BY sales_channel
ORDER BY net_sales DESC
"""

BUSINESS_CHANNEL_SQL = """
SELECT
    CASE
        WHEN sales_channel IN ('Online', 'Mobile App') THEN '线上'
        ELSE '线下'
    END AS channel_group,
    ROUND(SUM(sales_amount), 2) AS net_sales,
    COUNT(DISTINCT transaction_id) AS order_count,
    ROUND(SUM(sales_amount) / COUNT(DISTINCT transaction_id), 2) AS avg_order_value
FROM fact_sales
GROUP BY channel_group
ORDER BY net_sales DESC
"""


def is_channel_diagnostic_question(question: str) -> bool:
    asks_why = "为什么" in question or "原因" in question or "怎么回事" in question
    mentions_channel = any(word in question for word in ("渠道", "线上", "线下", "网页端", "手机端", "门店"))
    return asks_why and mentions_channel


def _row_for(frame: pd.DataFrame, column: str, value: str) -> pd.Series | None:
    matched = frame[frame[column] == value]
    return None if matched.empty else matched.iloc[0]


def diagnose_channel_performance(
    question: str,
    db_path: str | Path | None = None,
) -> dict[str, object] | None:
    if not is_channel_diagnostic_question(question):
        return None

    raw = run_sql(RAW_CHANNEL_SQL, db_path)
    grouped = run_sql(BUSINESS_CHANNEL_SQL, db_path)

    web = _row_for(raw, "sales_channel", "Online")
    store = _row_for(raw, "sales_channel", "In-Store")
    online_group = _row_for(grouped, "channel_group", "线上")
    offline_group = _row_for(grouped, "channel_group", "线下")

    if web is None or store is None or online_group is None or offline_group is None:
        return None

    raw_rank = int(raw.reset_index().index[raw["sales_channel"] == "Online"][0]) + 1
    premise = (
        f"按三个原始渠道分别比较，网页端净销售额为 {float(web['net_sales']) / 10000:,.2f} 万，"
        f"排名第 {raw_rank}。"
    )
    if float(online_group["net_sales"]) >= float(offline_group["net_sales"]):
        premise += (
            f"但按业务口径把网页端和手机端合并为线上后，线上净销售额为 "
            f"{float(online_group['net_sales']) / 10000:,.2f} 万，高于线下的 "
            f"{float(offline_group['net_sales']) / 10000:,.2f} 万，所以“线上表现最差”这个前提不成立。"
        )
    else:
        premise += (
            f"按业务口径合并后，线上净销售额仍低于线下，“线上较弱”的前提成立。"
        )

    order_gap_pct = (float(web["order_count"]) - float(store["order_count"])) / float(store["order_count"]) * 100
    aov_gap_pct = (float(web["avg_order_value"]) - float(store["avg_order_value"])) / float(store["avg_order_value"]) * 100
    decomposition = (
        f"如果只看网页端与线下门店的差距，网页端订单数相对线下门店 "
        f"{order_gap_pct:+.1f}%，客单价相对线下门店 {aov_gap_pct:+.1f}%。"
    )
    boundary = (
        "这些数据只能说明差距由订单量和客单价怎样构成，不能证明流量、活动、库存或服务是原因；"
        "要回答真正的业务原因，还需要相应字段或人工信息。"
    )

    raw_display = raw.copy()
    raw_display["sales_channel"] = raw_display["sales_channel"].replace(
        {"Online": "网页端", "Mobile App": "手机端", "In-Store": "线下门店"}
    )

    return {
        "question": question,
        "result": grouped,
        "explanation": f"{premise}\n\n{decomposition}\n\n{boundary}",
        "sql": f"-- 原始渠道拆分\n{RAW_CHANNEL_SQL.strip()}\n\n-- 线上/线下业务口径\n{BUSINESS_CHANNEL_SQL.strip()}",
        "diagnostic_tables": [("原始渠道指标拆解", raw_display)],
        "followups": [
            "线上和线下分别由哪些品类贡献？",
            "网页端最近 6 个月的净销售额趋势如何？",
            "网页端和线下门店在不同地区的净销售额如何？",
        ],
        "diagnostic_type": "channel_performance",
    }
