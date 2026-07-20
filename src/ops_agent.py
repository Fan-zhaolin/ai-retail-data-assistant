from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path
import json
import re
import sqlite3
from uuid import uuid4

from src.db import DB_PATH
from src.ops_data import DEMO_TODAY, ensure_operations_data


ACTION_DB_PATH = Path("data/agent_actions.db")
ORDER_ID_PATTERN = re.compile(r"\bT\d{7}\b", re.IGNORECASE)
PRODUCT_ID_PATTERN = re.compile(r"\bP\d{4}\b", re.IGNORECASE)

CATEGORY_ALIASES = {
    "美妆": "Beauty",
    "电子产品": "Electronics",
    "电子": "Electronics",
    "食品杂货": "Groceries",
    "食品": "Groceries",
    "图书": "Books",
    "服装": "Clothing",
    "运动": "Sports",
    "玩具": "Toys",
    "家居": "Home",
}

STATUS_LABELS = {
    "Processing": "处理中",
    "Shipped": "已发货",
    "Delivered": "已送达",
}

STOCK_LABELS = {"Low": "低库存", "Healthy": "库存正常"}


def _resolve_analytics_db(db_path: str | Path | None) -> Path:
    return Path(db_path) if db_path is not None else DB_PATH


def _resolve_action_db(action_db_path: str | Path | None) -> Path:
    return Path(action_db_path) if action_db_path is not None else ACTION_DB_PATH


def _read_one(sql: str, params: tuple[object, ...], db_path: str | Path | None) -> dict[str, object] | None:
    target = _resolve_analytics_db(db_path)
    ensure_operations_data(target)
    uri = f"file:{target.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        row = conn.execute(sql, params).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _read_all(sql: str, params: tuple[object, ...], db_path: str | Path | None) -> list[dict[str, object]]:
    target = _resolve_analytics_db(db_path)
    ensure_operations_data(target)
    uri = f"file:{target.resolve().as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA query_only = ON")
        return [dict(row) for row in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def ensure_action_store(action_db_path: str | Path | None = None) -> Path:
    target = _resolve_action_db(action_db_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(target, timeout=5)
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS return_requests (
                request_id TEXT PRIMARY KEY,
                idempotency_key TEXT NOT NULL UNIQUE,
                order_id TEXT NOT NULL,
                reason TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                demo_mode INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS agent_audit (
                event_id TEXT PRIMARY KEY,
                session_id TEXT NOT NULL,
                event_time TEXT NOT NULL,
                route TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                status TEXT NOT NULL,
                detail TEXT NOT NULL
            );
            """
        )
        conn.commit()
    finally:
        conn.close()
    return target


def _audit(
    session_id: str,
    route: str,
    tool_name: str,
    status: str,
    detail: str,
    action_db_path: str | Path | None,
) -> None:
    target = ensure_action_store(action_db_path)
    conn = sqlite3.connect(target, timeout=5)
    try:
        conn.execute(
            """
            INSERT INTO agent_audit(event_id, session_id, event_time, route, tool_name, status, detail)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                session_id,
                datetime.now(timezone.utc).isoformat(),
                route,
                tool_name,
                status,
                detail[:1000],
            ),
        )
        conn.commit()
    finally:
        conn.close()


def query_order(order_id: str, db_path: str | Path | None = None) -> dict[str, object] | None:
    return _read_one(
        """
        SELECT order_id, order_date, delivered_date, product_id, product_name, category,
               quantity, order_amount, sales_channel, region, order_status, demo_data
        FROM ops_orders
        WHERE UPPER(order_id) = UPPER(?)
        """,
        (order_id,),
        db_path,
    )


def query_inventory(
    product_query: str,
    db_path: str | Path | None = None,
) -> list[dict[str, object]]:
    product_id = PRODUCT_ID_PATTERN.search(product_query)
    if product_id:
        return _read_all(
            """
            SELECT product_id, product_name, category, available_qty, reserved_qty,
                   reorder_point, stock_status, updated_at, demo_data
            FROM inventory_snapshot
            WHERE UPPER(product_id) = UPPER(?)
            """,
            (product_id.group(0),),
            db_path,
        )
    keyword = product_query.strip()
    if not keyword:
        return []
    return _read_all(
        """
        SELECT product_id, product_name, category, available_qty, reserved_qty,
               reorder_point, stock_status, updated_at, demo_data
        FROM inventory_snapshot
        WHERE LOWER(product_name) LIKE LOWER(?)
        ORDER BY product_id
        LIMIT 10
        """,
        (f"%{keyword}%",),
        db_path,
    )


def _extract_category(text: str) -> str | None:
    for alias, category in CATEGORY_ALIASES.items():
        if alias in text:
            return category
    return None


def query_return_policy(
    category: str | None,
    db_path: str | Path | None = None,
) -> list[dict[str, object]]:
    if category:
        return _read_all(
            """
            SELECT category, return_window_days, opened_allowed, refund_method,
                   policy_note, effective_date, demo_data
            FROM return_policies
            WHERE category = ?
            """,
            (category,),
            db_path,
        )
    return _read_all(
        """
        SELECT category, return_window_days, opened_allowed, refund_method,
               policy_note, effective_date, demo_data
        FROM return_policies
        ORDER BY category
        """,
        (),
        db_path,
    )


def assess_return_eligibility(
    order: dict[str, object],
    policy: dict[str, object],
    today: date = DEMO_TODAY,
) -> dict[str, object]:
    if order.get("order_status") != "Delivered" or not order.get("delivered_date"):
        return {
            "eligible": False,
            "reason": "订单尚未送达，不能创建退货申请。",
            "days_since_delivery": None,
        }
    delivered = date.fromisoformat(str(order["delivered_date"]))
    days_since_delivery = (today - delivered).days
    window_days = int(policy["return_window_days"])
    if days_since_delivery < 0:
        return {
            "eligible": False,
            "reason": "订单送达日期晚于演示日期，数据状态异常。",
            "days_since_delivery": days_since_delivery,
        }
    if days_since_delivery > window_days:
        return {
            "eligible": False,
            "reason": f"已送达 {days_since_delivery} 天，超过 {window_days} 天申请窗口。",
            "days_since_delivery": days_since_delivery,
        }
    return {
        "eligible": True,
        "reason": (
            f"已送达 {days_since_delivery} 天，仍在 {window_days} 天申请窗口内；"
            "这里只表示可以提交申请，最终结果仍需售后人员复核。"
        ),
        "days_since_delivery": days_since_delivery,
    }


def _reason_from_message(message: str) -> str:
    match = re.search(r"(?:原因是|原因|因为)[:：]?\s*(.+)$", message)
    if match:
        return match.group(1).strip()[:200]
    return "用户未补充具体原因，提交前需人工补充"


def prepare_return_request(
    order_id: str,
    reason: str,
    db_path: str | Path | None = None,
) -> dict[str, object]:
    order = query_order(order_id, db_path)
    if order is None:
        return {"eligible": False, "reason": f"没有找到订单 {order_id}。", "order": None}
    policy_rows = query_return_policy(str(order["category"]), db_path)
    if not policy_rows:
        return {
            "eligible": False,
            "reason": f"没有找到 {order['category']} 的退货政策。",
            "order": order,
        }
    policy = policy_rows[0]
    eligibility = assess_return_eligibility(order, policy)
    proposal = {
        "order": order,
        "policy": policy,
        "eligibility": eligibility,
        "eligible": bool(eligibility["eligible"]),
        "reason": reason,
        "requires_approval": bool(eligibility["eligible"]),
    }
    if proposal["eligible"]:
        normalized = f"{str(order_id).upper()}|{reason.strip().lower()}"
        proposal["idempotency_key"] = sha256(normalized.encode("utf-8")).hexdigest()
    return proposal


def execute_return_request(
    proposal: dict[str, object],
    approved: bool,
    action_db_path: str | Path | None = None,
    session_id: str = "local-demo",
) -> dict[str, object]:
    if not approved:
        raise PermissionError("写操作未获人工批准，已阻止执行。")
    if not proposal.get("eligible") or not proposal.get("requires_approval"):
        raise ValueError("该申请不满足提交条件。")
    order = proposal.get("order")
    if not isinstance(order, dict) or not proposal.get("idempotency_key"):
        raise ValueError("退货申请缺少订单或幂等标识。")

    target = ensure_action_store(action_db_path)
    idempotency_key = str(proposal["idempotency_key"])
    conn = sqlite3.connect(target, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        existing = conn.execute(
            "SELECT * FROM return_requests WHERE idempotency_key = ?",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            result = dict(existing)
            result["idempotent_replay"] = True
            _audit(
                session_id,
                "return_request",
                "create_return_request",
                "idempotent_replay",
                json.dumps(
                    {"request_id": result["request_id"], "order_id": result["order_id"]},
                    ensure_ascii=False,
                ),
                action_db_path,
            )
            return result

        request_id = f"RR-{uuid4().hex[:10].upper()}"
        created_at = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            INSERT INTO return_requests(
                request_id, idempotency_key, order_id, reason, status, created_at, demo_mode
            ) VALUES (?, ?, ?, ?, ?, ?, 1)
            """,
            (
                request_id,
                idempotency_key,
                str(order["order_id"]),
                str(proposal["reason"]),
                "Pending human review",
                created_at,
            ),
        )
        conn.commit()
        result = {
            "request_id": request_id,
            "idempotency_key": idempotency_key,
            "order_id": str(order["order_id"]),
            "reason": str(proposal["reason"]),
            "status": "Pending human review",
            "created_at": created_at,
            "demo_mode": 1,
            "idempotent_replay": False,
        }
    finally:
        conn.close()

    _audit(
        session_id,
        "return_request",
        "create_return_request",
        "success",
        json.dumps({"request_id": result["request_id"], "order_id": result["order_id"]}, ensure_ascii=False),
        action_db_path,
    )
    return result


def _trace(tool: str, status: str, detail: str, risk: str = "read") -> dict[str, str]:
    return {"tool": tool, "status": status, "detail": detail, "risk": risk}


def run_ops_agent(
    message: str,
    db_path: str | Path | None = None,
    action_db_path: str | Path | None = None,
    session_id: str = "local-demo",
) -> dict[str, object]:
    """Route an operations request through an allowlisted, auditable tool workflow."""
    query = message.strip()
    order_match = ORDER_ID_PATTERN.search(query)
    product_match = PRODUCT_ID_PATTERN.search(query)
    mentions_return = any(word in query for word in ("退货", "退款", "退换"))
    mentions_policy = any(word in query for word in ("政策", "规则", "几天", "期限"))
    mentions_inventory = any(word in query for word in ("库存", "补货", "缺货"))
    mentions_order = any(word in query for word in ("订单", "物流", "到哪", "发货"))

    route = "clarification"
    trace: list[dict[str, str]] = []
    result: dict[str, object] = {"route": route, "trace": trace, "requires_approval": False}

    if mentions_return and order_match:
        route = "return_request"
        order_id = order_match.group(0).upper()
        reason = _reason_from_message(query)
        proposal = prepare_return_request(order_id, reason, db_path)
        order = proposal.get("order")
        if order is None:
            trace.append(_trace("query_order", "not_found", f"没有找到订单 {order_id}"))
            response = f"没有找到订单 {order_id}，未继续执行退货流程。"
        else:
            trace.append(_trace("query_order", "success", f"找到订单 {order_id}"))
            trace.append(
                _trace(
                    "retrieve_return_policy",
                    "success",
                    f"读取 {order['category']} 的演示退货政策",
                )
            )
            eligibility = proposal["eligibility"]
            trace.append(
                _trace(
                    "assess_return_eligibility",
                    "eligible" if eligibility["eligible"] else "blocked",
                    str(eligibility["reason"]),
                )
            )
            if proposal["eligible"]:
                trace.append(
                    _trace(
                        "create_return_request",
                        "waiting_approval",
                        "写操作已暂停，等待人工确认",
                        risk="write",
                    )
                )
                response = (
                    f"订单 {order_id} 可以提交退货申请。{eligibility['reason']}"
                    "系统尚未写入申请，需你明确确认。"
                )
            else:
                response = f"订单 {order_id} 当前不能提交退货申请：{eligibility['reason']}"
        result.update(
            {
                "route": route,
                "response": response,
                "proposal": proposal,
                "requires_approval": bool(proposal.get("requires_approval")),
            }
        )
    elif mentions_policy and not order_match:
        route = "return_policy"
        category = _extract_category(query)
        policies = query_return_policy(category, db_path)
        trace.append(
            _trace(
                "retrieve_return_policy",
                "success" if policies else "not_found",
                f"读取{category or '全部品类'}演示政策",
            )
        )
        if category and policies:
            policy = policies[0]
            opened = "允许拆封后申请" if policy["opened_allowed"] else "拆封后需人工复核"
            response = (
                f"{category} 的演示退货窗口为 {policy['return_window_days']} 天，{opened}。"
                f"{policy['policy_note']}"
            )
        elif policies:
            response = "请指定品类；当前可查询图书、美妆、电子产品、服装、食品、家居、运动和玩具等政策。"
        else:
            response = "没有找到对应品类的退货政策。"
        result.update({"route": route, "response": response, "policies": policies})
    elif mentions_return and not order_match:
        route = "return_request"
        trace.append(_trace("extract_order_id", "needs_input", "缺少形如 T0000064 的订单号"))
        result.update(
            {
                "route": route,
                "response": "请补充订单号，例如：订单 T0000064 想退货，原因是尺寸不合适。",
            }
        )
    elif mentions_inventory:
        route = "inventory_lookup"
        if not product_match:
            trace.append(_trace("extract_product_id", "needs_input", "缺少形如 P1025 的商品编号"))
            result.update(
                {
                    "route": route,
                    "response": "请补充商品编号，例如：P1025 当前库存是否需要补货？",
                    "items": [],
                }
            )
        else:
            items = query_inventory(product_match.group(0), db_path)
            if items:
                item = items[0]
                trace.append(_trace("query_inventory", "success", f"读取商品 {item['product_id']} 库存快照"))
                response = (
                    f"{item['product_id']}（{item['product_name']}）可用库存 {item['available_qty']}，"
                    f"补货点 {item['reorder_point']}，状态为{STOCK_LABELS.get(str(item['stock_status']), item['stock_status'])}。"
                )
            else:
                trace.append(_trace("query_inventory", "not_found", "未找到商品库存"))
                response = f"没有找到 {product_match.group(0).upper()} 的库存记录。"
            result.update({"route": route, "response": response, "items": items})
    elif order_match:
        route = "order_lookup"
        order_id = order_match.group(0).upper()
        order = query_order(order_id, db_path)
        if order:
            trace.append(_trace("query_order", "success", f"找到订单 {order_id}"))
            response = (
                f"订单 {order_id} 状态为{STATUS_LABELS.get(str(order['order_status']), order['order_status'])}，"
                f"商品为 {order['product_name']}，金额 {float(order['order_amount']):,.2f} 元。"
            )
        else:
            trace.append(_trace("query_order", "not_found", f"没有找到订单 {order_id}"))
            response = f"没有找到订单 {order_id}。"
        result.update({"route": route, "response": response, "order": order})
    else:
        trace.append(
            _trace(
                "route_task",
                "needs_input",
                "当前只开放订单、库存和退货政策工具；经营分析请使用下方自然语言分析区",
            )
        )
        result.update(
            {
                "route": route,
                "response": "我暂时无法判断要调用哪个工具。你可以查询订单、库存、退货政策，或提交带订单号的退货申请。",
            }
        )

    for step in trace:
        _audit(
            session_id,
            str(result["route"]),
            step["tool"],
            step["status"],
            step["detail"],
            action_db_path,
        )
    return result


def read_audit_events(
    action_db_path: str | Path | None = None,
    session_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, object]]:
    target = ensure_action_store(action_db_path)
    conn = sqlite3.connect(target, timeout=5)
    conn.row_factory = sqlite3.Row
    try:
        if session_id:
            rows = conn.execute(
                """
                SELECT event_time, route, tool_name, status, detail
                FROM agent_audit
                WHERE session_id = ?
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT event_time, route, tool_name, status, detail
                FROM agent_audit
                ORDER BY rowid DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()
