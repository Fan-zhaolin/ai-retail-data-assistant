SCHEMA = """
表结构：

fact_sales(
    transaction_id,
    transaction_date,
    customer_id,
    customer_gender,
    customer_age_group,
    customer_segment,
    product_id,
    quantity,
    discount_pct,
    sales_amount,
    payment_method,
    sales_channel,
    region
)

dim_product(
    product_id,
    product_name,
    category,
    brand,
    unit_price
)

关联关系：
fact_sales.product_id = dim_product.product_id

指标口径：
净销售额 = SUM(fact_sales.sales_amount)
订单数 = COUNT(DISTINCT fact_sales.transaction_id)
客单价 = SUM(fact_sales.sales_amount) / COUNT(DISTINCT fact_sales.transaction_id)
销售件数 = SUM(fact_sales.quantity)
平均折扣 = AVG(fact_sales.discount_pct)
折前销售额 = SUM(dim_product.unit_price * fact_sales.quantity)，需要 JOIN dim_product
折扣金额 = 折前销售额 - 净销售额，需要 JOIN dim_product

字段约束：
discount_pct 的实际取值为 0、5、10、15、20、25、30，单位为百分数。
例如“折扣超过 20%”必须使用 discount_pct > 20，不能写成 discount_pct > 0.2。

中文业务词与数据库枚举映射：
图书 = Books
美妆 = Beauty
运动 = Sports
杂货、食品杂货 = Groceries
手机端 = Mobile App
门店、线下门店 = In-Store
网页端 = Online

数据能力边界：
当前数据不包含库存、成本、利润、门店、退货和商品评价字段。
customer_age_group、customer_segment 和 region 是交易发生时的标签，
不能当作稳定不变的客户属性。
"""


def build_sql_prompt(question: str) -> str:
    return f"""
你是一个严谨的数据分析助手。请根据用户问题生成 SQLite SQL。

要求：
1. 只返回一条 SQL，不要解释，不要使用 Markdown 代码围栏。
2. 只能使用给定表和字段，不能虚构字段。
3. 只能生成 SELECT 查询，禁止 DROP、DELETE、UPDATE、INSERT、ALTER、CREATE、REPLACE。
4. 需要商品品类、商品名称、品牌时，必须 JOIN dim_product。
5. 金额字段保留两位小数，可使用 ROUND。
6. 涉及图书、美妆、运动、杂货、手机端、门店或网页端时，必须使用上面的数据库枚举映射。
7. 如果问题涉及库存、成本、利润、门店、退货或商品评价等不支持字段，只返回：
SELECT '当前数据不包含所需字段，无法回答该问题。' AS message;
8. 如果问题需要按月份统计，SQLite 使用 strftime('%Y-%m', transaction_date)。
9. 除非用户明确要求，否则查询结果最多返回 30 行。
10. “最大折扣有多少条订单”中的订单数必须只统计 discount_pct 等于最大折扣的记录，例如 WHERE discount_pct = (SELECT MAX(discount_pct) FROM fact_sales)。
11. “不存在的品类”是查询该品类本身，应使用 category = '品类名'；不能把“不存在”理解成 category <> '品类名'。
12. 用户要求“折前销售额、折扣金额和净销售额”时，必须 JOIN dim_product，并按上面的指标口径计算。
13. 当同一题同时查询最高和最低月份时，不要把两个带 ORDER BY/LIMIT 的 SELECT 直接用 UNION ALL 连接。应先用 CTE 汇总月度数据，再用 WHERE net_sales = (SELECT MAX(net_sales) FROM monthly_sales) OR net_sales = (SELECT MIN(net_sales) FROM monthly_sales) 返回两行。
14. 当用户比较“线上和线下”时，线上必须合并 sales_channel IN ('Online', 'Mobile App') 并输出标签“线上”；线下使用 sales_channel = 'In-Store' 并输出标签“线下”。不能把线上只理解为 Online，也不能输出“网页端/门店”代替“线上/线下”。

{SCHEMA}

用户问题：{question}
"""
