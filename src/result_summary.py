from __future__ import annotations

import pandas as pd


LABELS = {
    "category": "品类",
    "product_name": "商品",
    "sales_channel": "渠道",
    "channel_group": "渠道口径",
    "region": "地区",
    "customer_segment": "用户分群",
    "month": "月份",
    "year_month": "月份",
    "date_month": "月份",
    "net_sales": "净销售额",
    "sales_amount": "净销售额",
    "total_sales": "净销售额",
    "order_count": "订单数",
    "transaction_count": "订单数",
    "avg_order_value": "客单价",
    "avg_discount": "平均折扣",
}

VALUE_LABELS = {
    "Online": "网页端",
    "Mobile App": "手机端",
    "In-Store": "线下门店",
    "Beauty": "美妆",
    "Books": "图书",
    "Clothing": "服装",
    "Electronics": "电子产品",
    "Groceries": "食品杂货",
    "Home & Kitchen": "家居厨具",
    "Sports": "运动",
}


def _format_value(column: str, value: object) -> str:
    number = float(value)
    lowered = column.lower()
    if any(word in lowered for word in ("sales", "amount", "revenue", "price", "value")):
        if abs(number) >= 10000:
            return f"{number / 10000:,.1f} 万元"
        return f"{number:,.2f} 元"
    if "count" in lowered or "quantity" in lowered:
        return f"{number:,.0f}"
    if "discount" in lowered or "rate" in lowered or "pct" in lowered:
        return f"{number:.1f}%"
    return f"{number:,.2f}"


def _format_period(value: object) -> str:
    parsed = pd.to_datetime(str(value), errors="coerce")
    if pd.isna(parsed):
        return str(value)
    return parsed.strftime("%Y年%m月")


def _display_value(value: object) -> str:
    return VALUE_LABELS.get(str(value), str(value))


def _trend_summary(result: pd.DataFrame, time_col: str, metric_col: str) -> str:
    dimensions = [
        column
        for column in result.columns
        if column not in (time_col, metric_col) and not pd.api.types.is_numeric_dtype(result[column])
    ]
    series_col = dimensions[0] if dimensions else None
    work = result.copy()
    work["__period"] = pd.to_datetime(work[time_col].astype(str), errors="coerce")
    work = work.dropna(subset=["__period", metric_col]).sort_values("__period")
    if work.empty:
        return "查询已完成，请以下方数据明细为准。"

    groups = work.groupby(series_col, sort=False) if series_col else [(None, work)]
    sentences: list[str] = []
    for name, group in list(groups)[:4]:
        group = group.sort_values("__period")
        first = group.iloc[0]
        latest = group.iloc[-1]
        peak = group.loc[group[metric_col].astype(float).idxmax()]
        first_value = float(first[metric_col])
        latest_value = float(latest[metric_col])
        change_text = "无法计算变化率"
        if first_value != 0:
            change = (latest_value - first_value) / abs(first_value) * 100
            direction = "增长" if change >= 0 else "下降"
            change_text = f"较起始月{direction} {abs(change):.1f}%"
        prefix = f"{_display_value(name)}：" if series_col else ""
        sentences.append(
            f"{prefix}{_format_period(latest[time_col])}为{_format_value(metric_col, latest_value)}，"
            f"{change_text}；峰值出现在{_format_period(peak[time_col])}，"
            f"为{_format_value(metric_col, peak[metric_col])}"
        )

    scope = "各渠道" if series_col == "sales_channel" else "各组" if series_col else "整体"
    return "；".join(sentences) + f"。以上是{scope}的描述性变化，现有结果不能证明波动原因。"


def summarize_result(question: str, result: pd.DataFrame) -> str:
    """Build a factual result summary without asking an LLM to repeat numbers."""
    del question
    if result.empty:
        return "没有匹配结果。"

    numeric_cols = result.select_dtypes(include="number").columns.tolist()
    text_cols = [column for column in result.columns if column not in numeric_cols]
    if not numeric_cols:
        return f"查询返回 {len(result)} 条记录，请查看下方数据明细。"

    metric_col = numeric_cols[0]
    time_cols = [column for column in text_cols if "month" in column.lower() or "date" in column.lower()]
    if time_cols and len(result) > 1:
        return _trend_summary(result, time_cols[0], metric_col)

    metric_name = LABELS.get(metric_col, metric_col)
    if len(result) == 1:
        other_text = [column for column in text_cols if pd.notna(result.iloc[0][column])]
        prefix = "，".join(
            f"{LABELS.get(column, column)}为{_display_value(result.iloc[0][column])}"
            for column in other_text[:2]
        )
        answer = f"{metric_name}为{_format_value(metric_col, result.iloc[0][metric_col])}"
        return f"{prefix}，{answer}。" if prefix else f"{answer}。"

    if text_cols:
        dimension = text_cols[0]
        clean = result.dropna(subset=[metric_col])
        top = clean.loc[clean[metric_col].astype(float).idxmax()]
        bottom = clean.loc[clean[metric_col].astype(float).idxmin()]
        dimension_name = LABELS.get(dimension, dimension)
        return (
            f"{dimension_name}中，{_display_value(top[dimension])}的{metric_name}最高，"
            f"为{_format_value(metric_col, top[metric_col])}；"
            f"{_display_value(bottom[dimension])}最低，为{_format_value(metric_col, bottom[metric_col])}。"
            "这是结果对比，不代表造成差异的原因。"
        )

    return f"{metric_name}为{_format_value(metric_col, result.iloc[0][metric_col])}。"
