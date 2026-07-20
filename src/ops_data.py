from __future__ import annotations

from datetime import date
from pathlib import Path
import sqlite3

import pandas as pd


DEMO_TODAY = date(2025, 12, 31)


POLICY_OVERRIDES = {
    "Beauty": (14, False, "已拆封的个人护理类商品需人工复核。"),
    "Electronics": (14, False, "需保留完整配件和包装，质量问题转人工复核。"),
    "Groceries": (7, False, "食品类仅支持未拆封商品申请。"),
    "Toys": (30, True, "需保证主体和配件完整。"),
}


def _status_for_order(order_date: pd.Timestamp) -> tuple[str, str | None]:
    age_days = (DEMO_TODAY - order_date.date()).days
    if age_days <= 1:
        return "Processing", None
    if age_days <= 4:
        return "Shipped", None
    delivered = (order_date + pd.Timedelta(days=3)).date().isoformat()
    return "Delivered", delivered


def build_operations_tables(
    conn: sqlite3.Connection,
    fact_sales: pd.DataFrame,
    dim_product: pd.DataFrame,
) -> None:
    """Build deterministic demo operations tables from the public sales dataset.

    These tables are intentionally marked as synthetic. They let the prototype
    demonstrate order, inventory and return workflows without pretending that
    the public dataset contains real fulfilment or after-sales records.
    """
    products = dim_product[["product_id", "product_name", "category", "brand"]].copy()
    orders = fact_sales.merge(products, on="product_id", how="left")
    order_dates = pd.to_datetime(orders["transaction_date"], errors="raise")
    statuses = order_dates.apply(_status_for_order)
    orders["order_status"] = statuses.map(lambda value: value[0])
    orders["delivered_date"] = statuses.map(lambda value: value[1])
    orders["order_date"] = order_dates.dt.strftime("%Y-%m-%d")
    orders["demo_data"] = 1
    ops_orders = orders[
        [
            "transaction_id",
            "order_date",
            "delivered_date",
            "customer_id",
            "product_id",
            "product_name",
            "category",
            "quantity",
            "sales_amount",
            "sales_channel",
            "region",
            "order_status",
            "demo_data",
        ]
    ].rename(columns={"transaction_id": "order_id", "sales_amount": "order_amount"})

    inventory = products.copy()
    product_number = inventory["product_id"].astype(str).str.extract(r"(\d+)")[0].fillna("0").astype(int)
    inventory["on_hand_qty"] = 20 + (product_number * 37) % 181
    inventory["reserved_qty"] = (product_number * 13) % 16
    inventory["available_qty"] = inventory["on_hand_qty"] - inventory["reserved_qty"]
    inventory["reorder_point"] = 30 + (product_number % 4) * 10
    inventory["stock_status"] = inventory.apply(
        lambda row: "Low" if int(row["available_qty"]) <= int(row["reorder_point"]) else "Healthy",
        axis=1,
    )
    inventory["updated_at"] = DEMO_TODAY.isoformat()
    inventory["demo_data"] = 1

    categories = sorted(products["category"].dropna().astype(str).unique().tolist())
    policy_rows = []
    for category in categories:
        window_days, opened_allowed, note = POLICY_OVERRIDES.get(
            category,
            (30, True, "商品需保持完整；最终结果由售后人员复核。"),
        )
        policy_rows.append(
            {
                "category": category,
                "return_window_days": window_days,
                "opened_allowed": int(opened_allowed),
                "refund_method": "Original payment method",
                "policy_note": note,
                "effective_date": "2025-01-01",
                "demo_data": 1,
            }
        )
    policies = pd.DataFrame(policy_rows)

    ops_orders.to_sql("ops_orders", conn, if_exists="replace", index=False)
    inventory.to_sql("inventory_snapshot", conn, if_exists="replace", index=False)
    policies.to_sql("return_policies", conn, if_exists="replace", index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ops_orders_id ON ops_orders(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ops_orders_product ON ops_orders(product_id)")
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_inventory_product ON inventory_snapshot(product_id)"
    )


def operations_data_is_ready(db_path: str | Path) -> bool:
    target = Path(db_path)
    if not target.exists():
        return False
    try:
        conn = sqlite3.connect(target, timeout=5)
        try:
            names = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                ).fetchall()
            }
            required = {"ops_orders", "inventory_snapshot", "return_policies"}
            return required.issubset(names)
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def ensure_operations_data(db_path: str | Path) -> None:
    """Add derived demo tables to an already-built generated SQLite database."""
    target = Path(db_path)
    if operations_data_is_ready(target):
        return
    if not target.exists():
        raise ValueError(f"分析数据库不存在：{target}")

    conn = sqlite3.connect(target, timeout=10)
    try:
        fact_sales = pd.read_sql_query("SELECT * FROM fact_sales", conn)
        dim_product = pd.read_sql_query("SELECT * FROM dim_product", conn)
        build_operations_tables(conn, fact_sales, dim_product)
        conn.commit()
    finally:
        conn.close()
