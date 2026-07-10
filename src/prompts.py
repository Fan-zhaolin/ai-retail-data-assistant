SCHEMA = '''
表结构：
fact_sales(
 transaction_id, transaction_date, customer_id,
 customer_gender, customer_age_group, customer_segment,
 product_id, quantity, discount_pct, sales_amount,
 payment_method, sales_channel, region
)
dim_product(
 product_id, product_name, category, brand, unit_price
)
关联关系：
fact_sales.product_id = dim_product.product_id
指标口径：
GMV / 销售额 = SUM(fact_sales.sales_amount)
订单数 = COUNT(DISTINCT fact_sales.transaction_id)
客单价 = SUM(fact_sales.sales_amount) / COUNT(DISTINCT fact_sales.transaction_id)
销售件数 = SUM(fact_sales.quantity)
平均折扣 = AVG(fact_sales.discount_pct)
'''
def build_sql_prompt(question: str) -> str:
 return f'''
你是一个严谨的数据分析助手。请根据用户问题生成 SQLite SQL。
要求：
1. 只能返回 SQL，不要解释。
2. 只能使用给定表和字段，不能虚构字段。
3. 只能生成 SELECT 查询。
4. 禁止 DROP、DELETE、UPDATE、INSERT、ALTER、CREATE、REPLACE。
5. 如果需要商品品类、商品名称、品牌，请 JOIN dim_product。
6. 金额字段保留两位小数，可使用 ROUND。
{SCHEMA}
用户问题：{question}
'''