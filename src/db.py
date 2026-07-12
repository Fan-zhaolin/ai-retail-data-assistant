from pathlib import Path
import sqlite3
import pandas as pd
RAW_FILE = Path("data/raw/retail_sales_dataset.csv")
DB_PATH = Path("data/app.db")
MAX_QUERY_PROGRESS_STEPS = 100_000
def load_raw_data() -> pd.DataFrame:
 df = pd.read_csv(RAW_FILE)
 df["transaction_date"] = pd.to_datetime(df["transaction_date"])
 return df
def build_database():
 df = load_raw_data()
 # 商品信息在数据中是稳定的，适合拆成商品维度表。
 dim_product = (
 df[["product_id", "product_name", "category", "brand", "unit_price"]]
 .drop_duplicates()
 .sort_values("product_id")
 )
 # customer_id 对应的 segment/region 在源数据中可能变化，
 # 因此第一版不拆静态用户维度，避免制造不严谨的数据假设。
 fact_sales = df[
 [
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
 ].copy()
 fact_sales["transaction_date"] = fact_sales["transaction_date"].dt.strftime("%Y-%m-%d")
 DB_PATH.parent.mkdir(parents=True, exist_ok=True)
 conn = sqlite3.connect(DB_PATH)
 dim_product.to_sql("dim_product", conn, if_exists="replace", index=False)
 fact_sales.to_sql("fact_sales", conn, if_exists="replace", index=False)
 # Keep common analytical queries responsive without relaxing read-only access.
 conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_sales_product_id ON fact_sales(product_id)")
 conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_sales_date ON fact_sales(transaction_date)")
 conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_sales_channel ON fact_sales(sales_channel)")
 conn.execute("CREATE INDEX IF NOT EXISTS idx_fact_sales_segment ON fact_sales(customer_segment)")
 conn.execute("CREATE INDEX IF NOT EXISTS idx_dim_product_category ON dim_product(category)")
 conn.close()
 print("database created:", DB_PATH)
 print("dim_product rows:", len(dim_product))
 print("fact_sales rows:", len(fact_sales))

def ensure_database() -> None:
    if not DB_PATH.exists():
        build_database()

def run_sql(sql: str) -> pd.DataFrame:
    ensure_database()
    uri = f"file:{DB_PATH.resolve().as_posix()}?mode=ro"

    with sqlite3.connect(uri, uri=True, timeout=5) as conn:
        conn.execute("PRAGMA query_only = ON")

        steps = 0

        def stop_expensive_query():
            nonlocal steps
            steps += 1
            return 1 if steps > MAX_QUERY_PROGRESS_STEPS else 0

        conn.set_progress_handler(stop_expensive_query, 1000)
        return pd.read_sql_query(sql, conn)
if __name__ == "__main__":
 build_database()
