# SQL 与项目字段速查表

这份速查表用于学习和面试训练。现阶段允许查看，不要求死记全部字段。

## 两张核心表

### fact_sales：每一行是一条销售交易

| 想查什么 | 字段名 | 含义 |
| --- | --- | --- |
| 订单 | `transaction_id` | 订单编号 |
| 日期 | `transaction_date` | 交易日期 |
| 客户 | `customer_id` | 客户编号 |
| 用户分层 | `customer_segment` | VIP、New、Loyal、Returning |
| 商品 | `product_id` | 商品编号，用于连接商品表 |
| 数量 | `quantity` | 购买件数 |
| 折扣 | `discount_pct` | 折扣百分数 |
| 净销售额 | `sales_amount` | 实际销售金额 |
| 渠道 | `sales_channel` | Online、In-Store、Mobile App |
| 地区 | `region` | Central、East、North、South、West |
| 支付方式 | `payment_method` | 支付方式 |

### dim_product：每一行是一个商品

| 想查什么 | 字段名 | 含义 |
| --- | --- | --- |
| 商品 | `product_id` | 商品编号，与事实表连接 |
| 商品名称 | `product_name` | 商品名称 |
| 品类 | `category` | 商品品类 |
| 品牌 | `brand` | 商品品牌 |
| 单价 | `unit_price` | 商品单价 |

## 什么时候需要 JOIN

只要问题包含商品名称、品类、品牌或单价，就需要连接 `dim_product`：

```sql
FROM fact_sales AS f
JOIN dim_product AS p
    ON f.product_id = p.product_id
```

只查询销售额、订单数、日期、用户分层、渠道或地区时，通常只用 `fact_sales`。

## 五个核心计算

```sql
-- 净销售额
SUM(sales_amount)

-- 订单数
COUNT(DISTINCT transaction_id)

-- 客单价
SUM(sales_amount) / COUNT(DISTINCT transaction_id)

-- 销售件数
SUM(quantity)

-- 平均折扣
AVG(discount_pct)
```

## 固定SQL骨架

```sql
SELECT
    分组字段,
    聚合计算 AS 结果名称
FROM 表名
WHERE 筛选条件
GROUP BY 分组字段
ORDER BY 结果名称 DESC;
```

理解顺序：

```text
FROM：数据从哪里来
WHERE：哪些行参与计算
GROUP BY：按照什么类别分别计算
SUM/COUNT/AVG：每一组计算什么
SELECT：最终显示什么
ORDER BY：结果怎样排列
```

## 当前学习要求

- 可以查看表结构和这张速查表。
- 必须能解释为什么选择这些字段。
- 必须能根据报错检查拼写、逗号、引号和 `BY`。
- 暂时不要求脱离提示手写复杂查询。
- 最终要求掌握常用句型，而不是背诵整个数据库。
