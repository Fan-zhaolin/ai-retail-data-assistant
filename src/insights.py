from pathlib import Path

from src.db import run_sql


CHANNEL_LABELS = {
    "Online": "网页端",
    "Mobile App": "手机端",
    "In-Store": "线下门店",
}

CATEGORY_LABELS = {
    "Beauty": "美妆",
    "Books": "图书",
    "Clothing": "服装",
    "Electronics": "电子产品",
    "Groceries": "食品杂货",
    "Home & Kitchen": "家居厨具",
    "Sports": "运动",
}


def get_executive_brief(db_path: str | Path | None = None) -> dict[str, object]:
    totals = run_sql(
        """
        SELECT
            ROUND(SUM(sales_amount), 2) AS net_sales,
            COUNT(DISTINCT transaction_id) AS order_count,
            ROUND(SUM(sales_amount) / COUNT(DISTINCT transaction_id), 2) AS avg_order_value
        FROM fact_sales
        """,
        db_path,
    ).iloc[0]

    monthly = run_sql(
        """
        SELECT
            strftime('%Y-%m', transaction_date) AS month,
            ROUND(SUM(sales_amount), 2) AS net_sales
        FROM fact_sales
        GROUP BY month
        ORDER BY month DESC
        LIMIT 2
        """,
        db_path,
    )

    latest_month = str(monthly.iloc[0]["month"])
    latest_sales = float(monthly.iloc[0]["net_sales"])
    previous_sales = float(monthly.iloc[1]["net_sales"]) if len(monthly) > 1 else None
    month_change_pct = None
    if previous_sales not in (None, 0):
        month_change_pct = (latest_sales - previous_sales) / previous_sales * 100

    channel = run_sql(
        """
        SELECT
            sales_channel,
            ROUND(SUM(sales_amount), 2) AS net_sales
        FROM fact_sales
        WHERE strftime('%Y-%m', transaction_date) = (
            SELECT MAX(strftime('%Y-%m', transaction_date)) FROM fact_sales
        )
        GROUP BY sales_channel
        ORDER BY net_sales DESC
        """,
        db_path,
    )

    category = run_sql(
        """
        SELECT
            p.category,
            ROUND(SUM(f.sales_amount), 2) AS net_sales
        FROM fact_sales AS f
        JOIN dim_product AS p ON f.product_id = p.product_id
        WHERE strftime('%Y-%m', f.transaction_date) = (
            SELECT MAX(strftime('%Y-%m', transaction_date)) FROM fact_sales
        )
        GROUP BY p.category
        ORDER BY net_sales DESC
        """,
        db_path,
    )

    declining_category = None
    if len(monthly) > 1:
        decline = run_sql(
            """
            WITH month_bounds AS (
                SELECT DISTINCT strftime('%Y-%m', transaction_date) AS month
                FROM fact_sales
                ORDER BY month DESC
                LIMIT 2
            ), category_sales AS (
                SELECT
                    p.category,
                    strftime('%Y-%m', f.transaction_date) AS month,
                    SUM(f.sales_amount) AS net_sales
                FROM fact_sales AS f
                JOIN dim_product AS p ON f.product_id = p.product_id
                WHERE strftime('%Y-%m', f.transaction_date) IN (SELECT month FROM month_bounds)
                GROUP BY p.category, month
            ), ranked_months AS (
                SELECT month, ROW_NUMBER() OVER (ORDER BY month DESC) AS month_rank
                FROM month_bounds
            )
            SELECT
                c.category,
                ROUND(SUM(CASE WHEN r.month_rank = 1 THEN c.net_sales ELSE 0 END), 2) AS latest_sales,
                ROUND(SUM(CASE WHEN r.month_rank = 2 THEN c.net_sales ELSE 0 END), 2) AS previous_sales,
                ROUND(
                    SUM(CASE WHEN r.month_rank = 1 THEN c.net_sales ELSE 0 END)
                    - SUM(CASE WHEN r.month_rank = 2 THEN c.net_sales ELSE 0 END),
                    2
                ) AS sales_change
            FROM category_sales AS c
            JOIN ranked_months AS r ON c.month = r.month
            GROUP BY c.category
            ORDER BY sales_change ASC
            LIMIT 1
            """,
            db_path,
        )
        if not decline.empty:
            row = decline.iloc[0]
            declining_category = {
                "category": str(row["category"]),
                "latest_sales": float(row["latest_sales"]),
                "previous_sales": float(row["previous_sales"]),
                "sales_change": float(row["sales_change"]),
            }

    return {
        "net_sales": float(totals["net_sales"]),
        "order_count": int(totals["order_count"]),
        "avg_order_value": float(totals["avg_order_value"]),
        "latest_month": latest_month,
        "latest_month_sales": latest_sales,
        "month_change_pct": month_change_pct,
        "top_channel": str(channel.iloc[0]["sales_channel"]) if not channel.empty else None,
        "top_channel_sales": float(channel.iloc[0]["net_sales"]) if not channel.empty else None,
        "bottom_channel": str(channel.iloc[-1]["sales_channel"]) if not channel.empty else None,
        "top_category": str(category.iloc[0]["category"]) if not category.empty else None,
        "declining_category": declining_category,
    }


def build_attention_items(brief: dict[str, object]) -> list[str]:
    items: list[str] = []
    change = brief.get("month_change_pct")
    if change is not None:
        direction = "增长" if float(change) >= 0 else "下降"
        items.append(
            f"{brief['latest_month']} 净销售额较上月{direction} {abs(float(change)):.1f}%。"
        )
    if brief.get("top_channel"):
        channel = CHANNEL_LABELS.get(str(brief["top_channel"]), str(brief["top_channel"]))
        items.append(
            f"最新月份表现最好的渠道是 {channel}，可继续拆解其品类贡献。"
        )
    decline = brief.get("declining_category")
    if isinstance(decline, dict) and float(decline["sales_change"]) < 0:
        category = CATEGORY_LABELS.get(str(decline["category"]), str(decline["category"]))
        items.append(
            f"{category}是最新月份下降金额最大的品类，建议继续查看渠道和地区分布。"
        )
    if not items:
        items.append("当前数据未发现可直接判断的月度下降信号，可从渠道和品类结构继续分析。")
    return items[:3]
