from src.semantic_model import build_query_rules, build_semantic_context, load_semantic_model


def build_sql_prompt(question: str) -> str:
    model = load_semantic_model()
    semantic_context = build_semantic_context(model)
    query_rules = build_query_rules(model)
    return f"""
你是一个严谨的数据分析助手。请根据用户问题生成 SQLite SQL。

要求：
{query_rules}

如果问题涉及能力边界中不支持的数据，只返回：
SELECT '当前数据不包含所需字段，无法回答该问题。' AS message;

{semantic_context}

用户问题：{question}
"""
