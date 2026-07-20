VALUE_LABELS = {
    "Beauty": "美妆",
    "Books": "图书",
    "Clothing": "服装",
    "Electronics": "电子产品",
    "Groceries": "食品杂货",
    "Home & Kitchen": "家居厨具",
    "Sports": "运动",
    "Online": "网页端",
    "Mobile App": "手机端",
    "In-Store": "线下门店",
}


def suggest_followups(
    question: str,
    result_columns: list[str] | None = None,
    context_values: dict[str, object] | None = None,
) -> list[str]:
    text = question.lower()
    columns = {column.lower() for column in (result_columns or [])}
    values = context_values or {}
    category = VALUE_LABELS.get(str(values.get("category", "")), str(values.get("category", "")))
    channel = VALUE_LABELS.get(
        str(values.get("sales_channel", "")), str(values.get("sales_channel", ""))
    )

    if "sales_channel" in columns:
        subject = f"{channel}渠道" if channel else "表现最好的渠道"
        suggestions = [
            f"{subject}主要由哪些品类贡献？",
            f"{subject}最近 6 个月的净销售额趋势如何？",
            f"{subject}的订单数和客单价分别是多少？",
        ]
    elif "category" in columns:
        subject = f"{category}品类" if category else "销售额最高的品类"
        suggestions = [
            f"{subject}在哪个销售渠道表现最好？",
            f"{subject}最近 6 个月的净销售额趋势如何？",
            f"{subject}的订单数和客单价分别是多少？",
        ]
    elif "month" in columns or "趋势" in question or "月份" in question:
        suggestions = [
            "净销售额最高和最低的月份分别是哪个月？",
            "最近一个月哪个品类下降最多？",
            "最近一个月不同渠道的净销售额分别是多少？",
        ]
    elif "customer_segment" in columns or "vip" in text:
        suggestions = [
            "VIP 用户主要通过哪些渠道购买？",
            "VIP 用户购买最多的品类是什么？",
            "VIP 与普通用户的客单价分别是多少？",
        ]
    elif "渠道" in question:
        suggestions = [
            "表现最好的渠道主要由哪些品类贡献？",
            "不同渠道最近 6 个月的净销售额趋势如何？",
            "不同渠道的订单数和客单价分别是多少？",
        ]
    elif "品类" in question:
        suggestions = [
            "销售额最高的品类在哪个销售渠道表现最好？",
            "销售额最高的品类最近 6 个月趋势如何？",
            "销售额最高的品类的订单数和客单价分别是多少？",
        ]
    else:
        suggestions = [
            "最近 6 个月的净销售额趋势如何？",
            "哪个品类的净销售额最高？",
            "不同销售渠道的订单数和客单价分别是多少？",
        ]

    return suggestions[:3]
