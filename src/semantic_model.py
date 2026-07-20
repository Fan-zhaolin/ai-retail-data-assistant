import json
from functools import lru_cache
from pathlib import Path


DEFAULT_MODEL_PATH = Path(__file__).resolve().parents[1] / "config" / "semantic_model.json"
REQUIRED_SECTIONS = {
    "tables",
    "joins",
    "metrics",
    "field_constraints",
    "synonyms",
    "unsupported_fields",
    "query_rules",
}


def validate_semantic_model(model: dict) -> None:
    missing = sorted(REQUIRED_SECTIONS - set(model))
    if missing:
        raise ValueError(f"语义配置缺少必要部分：{', '.join(missing)}")

    if not isinstance(model["tables"], dict) or not model["tables"]:
        raise ValueError("语义配置中的 tables 必须包含至少一张表。")
    if not isinstance(model["metrics"], dict) or not model["metrics"]:
        raise ValueError("语义配置中的 metrics 必须包含至少一个指标。")

    table_columns: dict[str, set[str]] = {}
    for table_name, table in model["tables"].items():
        columns = table.get("columns") if isinstance(table, dict) else None
        if not isinstance(columns, dict) or not columns:
            raise ValueError(f"表 {table_name} 没有配置 columns。")
        table_columns[table_name] = set(columns)

    for join in model["joins"]:
        if not isinstance(join, dict) or "left" not in join or "right" not in join:
            raise ValueError("每条 joins 配置都必须包含 left 和 right。")
        for endpoint in (join["left"], join["right"]):
            if "." not in endpoint:
                raise ValueError(f"关联字段格式错误：{endpoint}")
            table_name, column_name = endpoint.split(".", 1)
            if table_name not in table_columns or column_name not in table_columns[table_name]:
                raise ValueError(f"关联字段不存在：{endpoint}")


@lru_cache(maxsize=8)
def _load_cached(path_text: str, modified_ns: int) -> dict:
    del modified_ns
    with Path(path_text).open(encoding="utf-8") as file:
        model = json.load(file)
    validate_semantic_model(model)
    return model


def load_semantic_model(path: str | Path = DEFAULT_MODEL_PATH) -> dict:
    model_path = Path(path).resolve()
    if not model_path.exists():
        raise FileNotFoundError(f"找不到语义配置：{model_path}")
    return _load_cached(str(model_path), model_path.stat().st_mtime_ns)


def build_semantic_context(model: dict) -> str:
    validate_semantic_model(model)
    lines = [f"语义模型：{model.get('name', '未命名模型')}", "", "表结构："]

    for table_name, table in model["tables"].items():
        lines.append(f"{table_name}（{table.get('description', '')}）")
        for column_name, description in table["columns"].items():
            lines.append(f"- {column_name}: {description}")

    lines.extend(["", "关联关系："])
    for join in model["joins"]:
        lines.append(f"- {join['left']} = {join['right']}：{join.get('description', '')}")

    lines.extend(["", "指标口径："])
    for metric_name, formula in model["metrics"].items():
        lines.append(f"- {metric_name} = {formula}")

    lines.extend(["", "字段约束："])
    lines.extend(f"- {item}" for item in model["field_constraints"])

    lines.extend(["", "中文业务词与数据库值映射："])
    for label, value in model["synonyms"].items():
        lines.append(f"- {label} = {value}")

    lines.extend(["", "数据能力边界："])
    lines.append(f"- 当前数据不包含：{'、'.join(model['unsupported_fields'])}")
    return "\n".join(lines)


def build_query_rules(model: dict) -> str:
    validate_semantic_model(model)
    return "\n".join(
        f"{index}. {rule}" for index, rule in enumerate(model["query_rules"], start=1)
    )
