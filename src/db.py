from pathlib import Path
import sqlite3
from uuid import uuid4

import pandas as pd

from src.ops_data import build_operations_tables


RAW_FILE = Path("data/raw/retail_sales_dataset.csv")
DB_PATH = Path("data/app.db")
MAX_QUERY_PROGRESS_STEPS = 100_000
MAX_UPLOAD_ROWS = 250_000

PRODUCT_COLUMNS = ["product_id", "product_name", "category", "brand", "unit_price"]
FACT_COLUMNS = [
    "transaction_id",
    "transaction_date",
    "customer_id",
    "customer_gender",
    "customer_age_group",
    "customer_segment",
    "product_id",
    "quantity",
    "discount_pct",
    "sales_amount",
    "payment_method",
    "sales_channel",
    "region",
]
REQUIRED_COLUMNS = PRODUCT_COLUMNS + [column for column in FACT_COLUMNS if column not in PRODUCT_COLUMNS]
NUMERIC_COLUMNS = ["unit_price", "quantity", "discount_pct", "sales_amount"]


def _resolve_db_path(db_path: str | Path | None = None) -> Path:
    return Path(db_path) if db_path is not None else DB_PATH


def load_raw_data(raw_file: str | Path | None = None) -> pd.DataFrame:
    source = Path(raw_file) if raw_file is not None else RAW_FILE
    return validate_source_dataframe(pd.read_csv(source))


def validate_source_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        raise ValueError("上传的数据没有记录。")
    if len(df) > MAX_UPLOAD_ROWS:
        raise ValueError(f"演示版最多支持 {MAX_UPLOAD_ROWS:,} 行上传数据。")

    missing = sorted(set(REQUIRED_COLUMNS) - set(df.columns))
    if missing:
        raise ValueError(f"数据缺少必要字段：{', '.join(missing)}")

    cleaned = df[REQUIRED_COLUMNS].copy()
    try:
        cleaned["transaction_date"] = pd.to_datetime(cleaned["transaction_date"], errors="raise")
    except (TypeError, ValueError) as exc:
        raise ValueError("transaction_date 包含无法识别的日期。") from exc

    for column in NUMERIC_COLUMNS:
        try:
            cleaned[column] = pd.to_numeric(cleaned[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise ValueError(f"字段 {column} 包含非数字内容。") from exc

    if cleaned["product_id"].isna().any() or cleaned["product_id"].astype(str).str.strip().eq("").any():
        raise ValueError("product_id 不能为空。")

    product_variants = cleaned.groupby("product_id", dropna=False)[
        ["product_name", "category", "brand", "unit_price"]
    ].nunique(dropna=False)
    if (product_variants > 1).any(axis=None):
        unstable_ids = product_variants.index[(product_variants > 1).any(axis=1)].astype(str).tolist()
        preview = ", ".join(unstable_ids[:5])
        raise ValueError(f"同一 product_id 对应了多组商品属性：{preview}")

    return cleaned


def database_is_ready(db_path: str | Path | None = None) -> bool:
    """Return True only when the selected database can serve real queries."""
    target = _resolve_db_path(db_path)
    if not target.exists():
        return False

    uri = f"file:{target.resolve().as_posix()}?mode=ro"
    try:
        conn = sqlite3.connect(uri, uri=True, timeout=5)
        try:
            row = conn.execute("SELECT COUNT(*) FROM fact_sales").fetchone()
            return row is not None and int(row[0]) > 0
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def build_database_from_dataframe(
    df: pd.DataFrame,
    db_path: str | Path | None = None,
) -> dict[str, object]:
    cleaned = validate_source_dataframe(df)
    target = _resolve_db_path(db_path)

    dim_product = (
        cleaned[PRODUCT_COLUMNS]
        .drop_duplicates(subset=["product_id"])
        .sort_values("product_id")
    )
    # 用户分群和地区可能随交易变化，因此保留在事实表，避免固定成静态客户属性。
    fact_sales = cleaned[FACT_COLUMNS].copy()
    fact_sales["transaction_date"] = fact_sales["transaction_date"].dt.strftime("%Y-%m-%d")

    target.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target.with_name(f"{target.name}.{uuid4().hex}.tmp")
    try:
        conn = sqlite3.connect(temp_path)
        try:
            dim_product.to_sql("dim_product", conn, if_exists="replace", index=False)
            fact_sales.to_sql("fact_sales", conn, if_exists="replace", index=False)
            conn.execute("CREATE INDEX idx_fact_sales_product_id ON fact_sales(product_id)")
            conn.execute("CREATE INDEX idx_fact_sales_date ON fact_sales(transaction_date)")
            conn.execute("CREATE INDEX idx_fact_sales_channel ON fact_sales(sales_channel)")
            conn.execute("CREATE INDEX idx_fact_sales_segment ON fact_sales(customer_segment)")
            conn.execute("CREATE INDEX idx_dim_product_category ON dim_product(category)")
            build_operations_tables(conn, fact_sales, dim_product)
            conn.commit()
        finally:
            conn.close()

        # 同目录内原子替换，查询方只会看到旧完整库或新完整库。
        temp_path.replace(target)
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except PermissionError:
                pass

    return {
        "rows": len(fact_sales),
        "products": len(dim_product),
        "start_date": fact_sales["transaction_date"].min(),
        "end_date": fact_sales["transaction_date"].max(),
        "db_path": str(target),
    }


def build_database(
    raw_file: str | Path | None = None,
    db_path: str | Path | None = None,
) -> dict[str, object]:
    metadata = build_database_from_dataframe(load_raw_data(raw_file), db_path)
    print("database created:", metadata["db_path"])
    print("dim_product rows:", metadata["products"])
    print("fact_sales rows:", metadata["rows"])
    return metadata


def ensure_database(db_path: str | Path | None = None) -> None:
    target = _resolve_db_path(db_path)
    if database_is_ready(target):
        return
    if db_path is not None and target != DB_PATH:
        raise ValueError(f"临时数据源尚未准备好：{target}")
    build_database(db_path=target)


def run_sql(sql: str, db_path: str | Path | None = None) -> pd.DataFrame:
    target = _resolve_db_path(db_path)
    ensure_database(target if db_path is not None else None)
    uri = f"file:{target.resolve().as_posix()}?mode=ro"

    conn = sqlite3.connect(uri, uri=True, timeout=5)
    try:
        conn.execute("PRAGMA query_only = ON")
        steps = 0

        def stop_expensive_query():
            nonlocal steps
            steps += 1
            return 1 if steps > MAX_QUERY_PROGRESS_STEPS else 0

        conn.set_progress_handler(stop_expensive_query, 1000)
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


if __name__ == "__main__":
    build_database()
