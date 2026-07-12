# 数据字典
## fact_sales：销售事实表
- transaction_id：交易 ID
- transaction_date：交易日期
- customer_id：匿名客户 ID
- customer_gender：客户性别
- customer_age_group：客户年龄段
- customer_segment：客户分层，例如 VIP、New、Loyal、Returning
- product_id：商品 ID，关联 dim_product.product_id
- quantity：购买数量
- discount_pct：折扣百分比
- sales_amount：销售金额
- payment_method：支付方式
- sales_channel：销售渠道，例如 Online、In-Store、Mobile App
- region：销售区域
## dim_product：商品维度表
- product_id：商品 ID
- product_name：商品名称
- category：商品品类
- brand：品牌
- unit_price：商品单价
## 指标口径

- 净销售额：SUM(fact_sales.sales_amount)，计算方式为 unit_price × quantity × (1 - discount_pct / 100)
- 订单数：COUNT(DISTINCT fact_sales.transaction_id)
- 客单价：SUM(fact_sales.sales_amount) / COUNT(DISTINCT fact_sales.transaction_id)
- 销售件数：SUM(fact_sales.quantity)
- 平均折扣：AVG(fact_sales.discount_pct)

说明：discount_pct 的实际取值为 0、5、10、15、20、25、30，单位为百分数。例如“折扣超过 20%”应写为 discount_pct > 20。

- 线上（整体）：Online + Mobile App
- 线下（整体）：In-Store