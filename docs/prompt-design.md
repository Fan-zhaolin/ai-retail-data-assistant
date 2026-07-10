# Prompt 设计记录
## V1：只提供用户问题
问题：模型容易虚构字段，例如 revenue、order_amount。
## V2：加入 fact_sales 和 dim_product 表结构
效果：字段幻觉减少，能正确 JOIN 商品维度表。
## V3：加入指标口径
改动：明确 GMV、订单数、客单价、销售件数、平均折扣。
效果：客单价、GMV 类问题更稳定。
## V4：加入安全规则
改动：只允许 SELECT，禁止 DROP、DELETE、UPDATE、INSERT、ALTER、CREATE、REPLACE。
效果：危险请求可被安全校验拦截。