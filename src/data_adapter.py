import re

import pandas as pd


COLUMN_ALIASES = {
    "transaction_id": [
        "transaction_id", "order_id", "order_no", "order_number", "订单号", "订单编号", "交易编号", "流水号"
    ],
    "transaction_date": [
        "transaction_date", "order_date", "sales_date", "date", "交易日期", "订单日期", "下单日期", "销售日期", "日期"
    ],
    "customer_id": ["customer_id", "user_id", "member_id", "客户编号", "客户id", "用户id", "会员编号"],
    "customer_gender": ["customer_gender", "gender", "客户性别", "性别"],
    "customer_age_group": ["customer_age_group", "age_group", "年龄分组", "年龄段"],
    "customer_segment": ["customer_segment", "segment", "customer_level", "客户分群", "客户等级", "会员等级"],
    "product_id": ["product_id", "sku_id", "sku", "item_id", "商品编号", "商品id", "产品编号", "产品id", "sku编码"],
    "product_name": ["product_name", "item_name", "sku_name", "商品名称", "产品名称", "商品名"],
    "category": ["category", "product_category", "品类", "商品品类", "产品品类", "类别"],
    "brand": ["brand", "品牌"],
    "unit_price": ["unit_price", "price", "list_price", "单价", "商品单价", "标价"],
    "quantity": ["quantity", "qty", "sales_quantity", "数量", "销售数量", "件数"],
    "discount_pct": ["discount_pct", "discount", "discount_percent", "折扣", "折扣率", "折扣百分比"],
    "sales_amount": ["sales_amount", "net_sales", "revenue", "amount", "销售额", "净销售额", "实付金额", "成交金额"],
    "payment_method": ["payment_method", "payment", "支付方式", "付款方式"],
    "sales_channel": ["sales_channel", "channel", "销售渠道", "渠道", "订单渠道"],
    "region": ["region", "area", "province", "地区", "区域", "省份"],
}

CORE_REQUIRED = ["transaction_id", "transaction_date", "category", "sales_channel"]


def normalize_column_name(name: object) -> str:
    return re.sub(r"[\s_\-()%（）]+", "", str(name).strip().lower())


def detect_column_mapping(columns: list[object]) -> dict[str, str]:
    source_by_normalized = {normalize_column_name(column): str(column) for column in columns}
    mapping: dict[str, str] = {}
    used_sources: set[str] = set()

    for target, aliases in COLUMN_ALIASES.items():
        for alias in aliases:
            source = source_by_normalized.get(normalize_column_name(alias))
            if source and source not in used_sources:
                mapping[target] = source
                used_sources.add(source)
                break
    return mapping


def adapt_source_dataframe(df: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, object]]:
    if df.empty:
        raise ValueError("上传的数据没有记录。")

    mapping = detect_column_mapping(df.columns.tolist())
    missing_core = [field for field in CORE_REQUIRED if field not in mapping]
    if missing_core:
        labels = "、".join(missing_core)
        raise ValueError(
            f"无法识别必要业务字段：{labels}。请使用常见中英文字段名，或先整理成销售明细表。"
        )
    if "sales_amount" not in mapping and "unit_price" not in mapping:
        raise ValueError("至少需要销售额或单价字段，当前文件均未识别。")

    renamed = df.rename(columns={source: target for target, source in mapping.items()}).copy()
    filled_defaults: list[str] = []

    if "quantity" not in renamed:
        renamed["quantity"] = 1
        filled_defaults.append("quantity=1")
    if "discount_pct" not in renamed:
        renamed["discount_pct"] = 0
        filled_defaults.append("discount_pct=0")
    if "brand" not in renamed:
        renamed["brand"] = "未提供"
        filled_defaults.append("brand=未提供")
    if "product_name" not in renamed:
        renamed["product_name"] = renamed["category"].astype(str)
        filled_defaults.append("product_name=category")

    quantity = pd.to_numeric(renamed["quantity"], errors="coerce")
    discount = pd.to_numeric(renamed["discount_pct"], errors="coerce").fillna(0)
    if quantity.isna().any() or (quantity <= 0).any():
        raise ValueError("数量字段包含空值、非数字或小于等于 0 的内容。")

    if "sales_amount" not in renamed:
        price = pd.to_numeric(renamed["unit_price"], errors="coerce")
        if price.isna().any():
            raise ValueError("单价字段包含非数字内容，无法计算销售额。")
        renamed["sales_amount"] = price * quantity * (1 - discount / 100)
        filled_defaults.append("sales_amount=unit_price×quantity×折扣")

    if "unit_price" not in renamed:
        amount = pd.to_numeric(renamed["sales_amount"], errors="coerce")
        denominator = quantity * (1 - discount / 100)
        if amount.isna().any() or (denominator <= 0).any():
            raise ValueError("销售额或折扣字段无法用于推算单价。")
        renamed["unit_price"] = amount / denominator
        filled_defaults.append("unit_price=由销售额反推")

    if "product_id" not in renamed:
        identity = (
            renamed[["product_name", "category", "brand", "unit_price"]]
            .astype(str)
            .agg("|".join, axis=1)
        )
        codes, _ = pd.factorize(identity, sort=True)
        renamed["product_id"] = [f"AUTO-P{code + 1:05d}" for code in codes]
        filled_defaults.append("product_id=按商品属性自动生成")

    optional_defaults = {
        "customer_id": "未提供",
        "customer_gender": "未提供",
        "customer_age_group": "未提供",
        "customer_segment": "未提供",
        "payment_method": "未提供",
        "region": "未提供",
    }
    for column, default in optional_defaults.items():
        if column not in renamed:
            renamed[column] = default
            filled_defaults.append(f"{column}={default}")

    report = {
        "mapping": mapping,
        "filled_defaults": filled_defaults,
        "unmapped_columns": [str(column) for column in df.columns if str(column) not in mapping.values()],
    }
    return renamed, report
