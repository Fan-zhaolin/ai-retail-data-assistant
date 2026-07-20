from pathlib import Path
import sqlite3
import tempfile
from uuid import uuid4

import pandas as pd
import plotly.express as px
import streamlit as st

from src.db import build_database_from_dataframe, ensure_database, run_sql
from src.data_adapter import adapt_source_dataframe
from src.diagnostics import diagnose_channel_performance
from src.evaluator import clean_sql, has_risky_intent, is_safe_sql
from src.followups import suggest_followups
from src.insights import build_attention_items, get_executive_brief
from src.llm import ask_llm
from src.ops_agent import execute_return_request, read_audit_events, run_ops_agent
from src.ops_data import DEMO_TODAY
from src.prompts import build_sql_prompt
from src.result_summary import summarize_result


MAX_QUESTION_LENGTH = 300
MAX_RESULT_ROWS = 1000
MAX_UPLOAD_BYTES = 20 * 1024 * 1024
EXAMPLE_QUESTIONS = [
    "哪个品类销售额最高？",
    "不同销售渠道的销售额分别是多少？",
    "2025 年每个月销售额趋势如何？",
    "VIP 用户的客单价是多少？",
]
AGENT_EXAMPLES = [
    "订单 T0000064 到哪了？",
    "P1025 当前库存是否需要补货？",
    "订单 T0000064 想退货，原因是尺寸不合适",
]

DISPLAY_NAMES = {
    "category": "品类",
    "product_name": "商品名称",
    "brand": "品牌",
    "sales_channel": "销售渠道",
    "channel_group": "渠道口径",
    "region": "地区",
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

CHANNEL_NAMES = {
    "Online": "网页端",
    "Mobile App": "手机端",
    "In-Store": "线下门店",
}

CATEGORY_NAMES = {
    "Beauty": "美妆",
    "Books": "图书",
    "Clothing": "服装",
    "Electronics": "电子产品",
    "Groceries": "食品杂货",
    "Home & Kitchen": "家居厨具",
    "Sports": "运动",
}


st.set_page_config(page_title="AI 零售经营分析助手", page_icon="📊", layout="wide")
st.markdown(
    """
    <style>
    .stApp { background: #f5f7fa; }
    .block-container { max-width: 1180px; padding-top: 2rem; padding-bottom: 4rem; }
    [data-testid="stMetric"] {
        background: #ffffff;
        border: 1px solid #e4e8ee;
        border-radius: 10px;
        padding: 14px 16px;
        min-height: 108px;
    }
    [data-testid="stMetricLabel"] { color: #52606d; }
    div[data-testid="stExpander"] {
        background: #ffffff;
        border: 1px solid #e4e8ee;
        border-radius: 10px;
    }
    .hero {
        background: #172b4d;
        color: white;
        border-radius: 14px;
        padding: 24px 28px;
        margin-bottom: 20px;
    }
    .hero h1 { color: white; margin: 0 0 8px 0; font-size: 2rem; }
    .hero p { color: #dce6f2; margin: 0; font-size: 1rem; }
    .insight-card {
        background: #ffffff;
        border-left: 4px solid #2f6fed;
        border-radius: 8px;
        padding: 14px 16px;
        margin: 8px 0;
        color: #172b4d;
    }
    .section-note { color: #68778a; margin-top: -8px; margin-bottom: 12px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def active_db_path() -> str | None:
    return st.session_state.get("active_db_path")


def source_label() -> str:
    return "当前会话上传数据" if active_db_path() else "公开零售演示数据"


@st.cache_data(show_spinner=False)
def load_overview(db_path_text: str | None) -> dict[str, str]:
    total_rows = run_sql("SELECT COUNT(*) AS value FROM fact_sales", db_path_text)["value"].iloc[0]
    product_count = run_sql(
        "SELECT COUNT(DISTINCT product_id) AS value FROM dim_product", db_path_text
    )["value"].iloc[0]
    date_range = run_sql(
        "SELECT MIN(transaction_date) AS start_date, MAX(transaction_date) AS end_date FROM fact_sales",
        db_path_text,
    )
    return {
        "total_rows": f"{int(total_rows):,}",
        "product_count": f"{int(product_count):,}",
        "start_date": str(date_range["start_date"].iloc[0]),
        "end_date": str(date_range["end_date"].iloc[0]),
    }


@st.cache_data(show_spinner=False)
def load_brief(db_path_text: str | None) -> dict[str, object]:
    return get_executive_brief(db_path_text)


def format_currency(value: float | int | None) -> str:
    if value is None:
        return "-"
    amount = float(value)
    if abs(amount) >= 10000:
        return f"{amount / 10000:,.2f} 万"
    return f"{amount:,.2f}"


def format_metric_value(column: str, value: object) -> str:
    if pd.isna(value):
        return "-"
    lowered = column.lower()
    if any(word in lowered for word in ("sales", "amount", "value", "price")):
        return format_currency(float(value))
    if isinstance(value, (int, float)):
        return f"{float(value):,.2f}" if isinstance(value, float) else f"{value:,}"
    return str(value)


def set_question(question: str, auto_run: bool = False) -> None:
    st.session_state.question = question
    st.session_state.auto_run = auto_run


def set_agent_query(query: str, auto_run: bool = False) -> None:
    st.session_state.agent_query = query
    st.session_state.agent_auto_run = auto_run


def action_db_path(db_path_text: str | None) -> str | None:
    if not db_path_text:
        return None
    return str(Path(db_path_text).with_name("agent_actions.db"))


def draw_chart(result: pd.DataFrame) -> None:
    numeric_cols = result.select_dtypes(include="number").columns.tolist()
    text_cols = [column for column in result.columns if column not in numeric_cols]
    if result.empty or not numeric_cols or not text_cols:
        st.info("当前结果不适合自动生成图表，可在下方查看数据明细。")
        return
    if len(result) == 1:
        st.info("当前结果只有一个汇总值，关键数字已在上方展示，无需绘制单根柱状图。")
        return

    time_cols = [column for column in text_cols if "month" in column.lower() or "date" in column.lower()]
    x_col = time_cols[0] if time_cols else text_cols[0]
    color_candidates = [column for column in text_cols if column != x_col]
    color_col = color_candidates[0] if color_candidates else None
    y_col = numeric_cols[0]
    chart_data = result.head(30).copy()
    display_x = DISPLAY_NAMES.get(x_col, x_col)
    display_y = DISPLAY_NAMES.get(y_col, y_col)
    display_color = DISPLAY_NAMES.get(color_col, color_col) if color_col else None
    rename_map = {x_col: display_x, y_col: display_y}
    if color_col:
        rename_map[color_col] = display_color
    chart_data = chart_data.rename(columns=rename_map)

    if x_col == "sales_channel":
        chart_data[display_x] = chart_data[display_x].replace(CHANNEL_NAMES)
    elif x_col == "category":
        chart_data[display_x] = chart_data[display_x].replace(CATEGORY_NAMES)
    if color_col == "sales_channel":
        chart_data[display_color] = chart_data[display_color].replace(CHANNEL_NAMES)
    elif color_col == "category":
        chart_data[display_color] = chart_data[display_color].replace(CATEGORY_NAMES)

    is_amount = any(word in y_col.lower() for word in ("sales", "amount", "revenue", "price", "value"))
    if is_amount and chart_data[display_y].abs().max() >= 10000:
        chart_data[display_y] = chart_data[display_y] / 10000
        display_y_with_unit = f"{display_y}（万元）"
        chart_data = chart_data.rename(columns={display_y: display_y_with_unit})
        display_y = display_y_with_unit

    chart_title = f"{display_y} / {display_x}"
    palette = ["#2F6FED", "#16A085", "#F39C12", "#8E6CEF", "#D35454", "#607D8B"]
    if time_cols:
        parsed_time = pd.to_datetime(chart_data[display_x], errors="coerce")
        if parsed_time.notna().all():
            chart_data[display_x] = parsed_time.dt.strftime("%Y年%m月")
        sort_columns = [display_x] + ([display_color] if display_color else [])
        chart_data = chart_data.sort_values(sort_columns)
        fig = px.line(
            chart_data,
            x=display_x,
            y=display_y,
            color=display_color,
            markers=True,
            title=chart_title,
            color_discrete_sequence=palette,
        )
        fig.update_traces(line=dict(width=2.5), marker=dict(size=7))
    else:
        fig = px.bar(
            chart_data,
            x=display_x,
            y=display_y,
            color=display_color,
            title=chart_title,
            color_discrete_sequence=palette,
        )
    fig.update_layout(
        height=380,
        margin=dict(l=10, r=10, t=50, b=10),
        plot_bgcolor="white",
        paper_bgcolor="white",
        font=dict(color="#263547"),
        bargap=0.48,
        hovermode="x unified" if time_cols else "closest",
        legend_title_text=display_color or "",
    )
    fig.update_yaxes(tickformat=",.2f" if is_amount else ",.0f", gridcolor="#E8EDF3")
    fig.update_xaxes(showgrid=False)
    st.plotly_chart(fig, width="stretch")


def render_data_source_panel() -> None:
    st.sidebar.header("数据源")
    st.sidebar.write(f"当前使用：{source_label()}")
    uploaded = st.sidebar.file_uploader(
        "上传销售明细 CSV",
        type=["csv"],
        help="自动识别常见中英文字段名；文件只用于当前会话，不覆盖公共演示数据库。",
    )

    if uploaded is not None and st.sidebar.button("校验并使用这份数据", type="primary"):
        if uploaded.size > MAX_UPLOAD_BYTES:
            st.sidebar.error("文件超过 20 MB，请先缩小数据量。")
        else:
            try:
                source_frame = pd.read_csv(uploaded)
                frame, adapter_report = adapt_source_dataframe(source_frame)
                session_dir = Path(tempfile.mkdtemp(prefix="ai-retail-session-"))
                session_db = session_dir / "app.db"
                metadata = build_database_from_dataframe(frame, session_db)
                previous = st.session_state.get("active_db_path")
                st.session_state.active_db_path = str(session_db)
                st.session_state.source_report = adapter_report
                st.session_state.analysis = None
                st.session_state.agent_result = None
                st.session_state.agent_execution = None
                st.cache_data.clear()
                if previous:
                    previous_path = Path(previous)
                    try:
                        previous_path.unlink(missing_ok=True)
                        previous_path.parent.rmdir()
                    except OSError:
                        pass
                st.sidebar.success(
                    f"已加载 {int(metadata['rows']):,} 行，日期范围 "
                    f"{metadata['start_date']} 至 {metadata['end_date']}。"
                )
                st.rerun()
            except (ValueError, pd.errors.ParserError) as exc:
                st.sidebar.error(str(exc))

    if active_db_path() and st.sidebar.button("恢复公开演示数据"):
        old_path = Path(st.session_state.active_db_path)
        st.session_state.active_db_path = None
        st.session_state.analysis = None
        st.session_state.agent_result = None
        st.session_state.agent_execution = None
        st.session_state.source_report = None
        st.cache_data.clear()
        try:
            old_path.unlink(missing_ok=True)
            old_path.parent.rmdir()
        except OSError:
            pass
        st.rerun()

    with st.sidebar.expander("数据适配说明"):
        st.write(
            "系统会识别订单号、日期、品类、渠道、销售额、单价等常见中英文字段名，并补全缺失的可选字段。"
        )
        st.caption("仍要求一张销售明细表，不支持自动合并任意多表、权限系统或企业数仓。")
        report = st.session_state.get("source_report")
        if report:
            st.write("本次字段映射：")
            for target, source in report["mapping"].items():
                st.write(f"{source} → {target}")
            if report["filled_defaults"]:
                st.caption("自动补全：" + "；".join(report["filled_defaults"]))


def render_executive_brief(db_path_text: str | None) -> None:
    overview = load_overview(db_path_text)
    brief = load_brief(db_path_text)

    st.subheader("经营简报")
    st.markdown(
        f'<p class="section-note">数据源：{source_label()}，最新数据月份：{brief["latest_month"]}</p>',
        unsafe_allow_html=True,
    )
    metric_cols = st.columns(4)
    metric_cols[0].metric("累计净销售额", format_currency(brief["net_sales"]))
    metric_cols[1].metric("累计订单数", f"{int(brief['order_count']):,}")
    metric_cols[2].metric("累计客单价", format_currency(brief["avg_order_value"]))
    change = brief.get("month_change_pct")
    metric_cols[3].metric(
        f"{brief['latest_month']} 净销售额",
        format_currency(brief["latest_month_sales"]),
        None if change is None else f"{float(change):+.1f}% 较上月",
    )

    left, right = st.columns([1.35, 1])
    with left:
        st.markdown("#### 值得关注")
        for item in build_attention_items(brief):
            st.markdown(f'<div class="insight-card">{item}</div>', unsafe_allow_html=True)
    with right:
        st.markdown("#### 数据状态")
        st.write(f"交易记录：{overview['total_rows']} 行")
        st.write(f"商品数量：{overview['product_count']} 个")
        st.write(f"日期范围：{overview['start_date']} 至 {overview['end_date']}")
        if brief.get("top_channel"):
            channel = CHANNEL_NAMES.get(str(brief["top_channel"]), str(brief["top_channel"]))
            st.write(f"最新月份领先渠道：{channel}")


def render_result_metrics(result: pd.DataFrame) -> None:
    if result.empty:
        return
    numeric_cols = result.select_dtypes(include="number").columns.tolist()[:3]
    if not numeric_cols:
        return
    columns = st.columns(len(numeric_cols))
    for container, column in zip(columns, numeric_cols):
        container.metric(
            DISPLAY_NAMES.get(column, column),
            format_metric_value(column, result.iloc[0][column]),
        )


def render_analysis(analysis: dict[str, object]) -> None:
    question = str(analysis["question"])
    sql = str(analysis["sql"])
    result = analysis["result"]
    explanation = str(analysis["explanation"])
    assert isinstance(result, pd.DataFrame)

    st.divider()
    st.subheader("分析结论")
    with st.container(border=True):
        st.markdown(explanation)
    if not analysis.get("diagnostic_type"):
        render_result_metrics(result)

    diagnostic_tables = analysis.get("diagnostic_tables", [])
    if diagnostic_tables:
        st.markdown("#### 指标拆解")
        for title, table in diagnostic_tables:
            st.markdown(f"**{title}**")
            st.dataframe(table.rename(columns=DISPLAY_NAMES), width="stretch", hide_index=True)

    st.markdown("#### 可视化")
    draw_chart(result)

    st.markdown("#### 继续分析")
    st.caption("点击一个问题继续探索，避免看完一张表就中断分析。")
    context_values = result.iloc[0].to_dict() if not result.empty else {}
    followups = analysis.get("followups") or suggest_followups(
        question, result.columns.tolist(), context_values
    )
    followup_cols = st.columns(3)
    for index, (container, followup) in enumerate(zip(followup_cols, followups)):
        container.button(
            followup,
            key=f"followup_{index}_{question}",
            width="stretch",
            on_click=set_question,
            args=(followup, True),
        )

    with st.expander("查看数据与计算依据"):
        st.success("SQL 已通过只读安全校验。")
        st.dataframe(result.rename(columns=DISPLAY_NAMES), width="stretch", hide_index=True)
        st.code(sql, language="sql")
        st.caption(f"本次查询返回 {len(result)} 行。数据表与 SQL 用于复核，不代表额外业务结论。")


def render_agent_result(result: dict[str, object], action_db: str | None) -> None:
    st.markdown("#### 执行结果")
    with st.container(border=True):
        st.write(str(result.get("response", "")))

    trace = result.get("trace") or []
    if trace:
        st.markdown("#### 工具调用轨迹")
        trace_frame = pd.DataFrame(trace).rename(
            columns={"tool": "工具", "status": "状态", "detail": "说明", "risk": "权限"}
        )
        st.dataframe(trace_frame, width="stretch", hide_index=True)

    proposal = result.get("proposal")
    execution = st.session_state.get("agent_execution")
    execution_matches = bool(
        execution
        and isinstance(proposal, dict)
        and execution.get("idempotency_key") == proposal.get("idempotency_key")
    )

    if execution_matches:
        replay = "（重复提交已通过幂等键复用原申请）" if execution.get("idempotent_replay") else ""
        st.success(
            f"已创建演示申请 {execution['request_id']}，状态：等待人工复核。{replay}"
        )
    elif result.get("requires_approval") and isinstance(proposal, dict):
        st.warning("检测到写操作：创建退货申请。当前已暂停，勾选确认前不会写入。")
        approval_key = str(proposal.get("idempotency_key", "pending"))[:12]
        approved = st.checkbox(
            "我确认这是演示操作，并批准创建退货申请",
            key=f"agent_approve_{approval_key}",
        )
        if st.button(
            "批准并创建申请",
            type="primary",
            disabled=not approved,
            key=f"agent_execute_{approval_key}",
        ):
            try:
                execution = execute_return_request(
                    proposal,
                    approved=True,
                    action_db_path=action_db,
                    session_id=st.session_state.agent_session_id,
                )
                st.session_state.agent_execution = execution
                st.rerun()
            except (PermissionError, ValueError) as exc:
                st.error(str(exc))

    with st.expander("查看当前会话审计日志"):
        events = read_audit_events(
            action_db_path=action_db,
            session_id=st.session_state.agent_session_id,
            limit=20,
        )
        if events:
            st.dataframe(
                pd.DataFrame(events).rename(
                    columns={
                        "event_time": "时间",
                        "route": "任务路由",
                        "tool_name": "工具",
                        "status": "状态",
                        "detail": "说明",
                    }
                ),
                width="stretch",
                hide_index=True,
            )
        else:
            st.caption("当前会话还没有审计记录。")


ensure_database()
if "history" not in st.session_state:
    st.session_state.history = []
if "question" not in st.session_state:
    st.session_state.question = EXAMPLE_QUESTIONS[0]
if "analysis" not in st.session_state:
    st.session_state.analysis = None
if "active_db_path" not in st.session_state:
    st.session_state.active_db_path = None
if "source_report" not in st.session_state:
    st.session_state.source_report = None
if "agent_query" not in st.session_state:
    st.session_state.agent_query = ""
if "agent_result" not in st.session_state:
    st.session_state.agent_result = None
if "agent_execution" not in st.session_state:
    st.session_state.agent_execution = None
if "agent_session_id" not in st.session_state:
    st.session_state.agent_session_id = uuid4().hex

render_data_source_panel()
current_db = active_db_path()

st.markdown(
    """
    <div class="hero">
      <h1>AI 零售经营分析助手</h1>
      <p>先展示经营重点，再用自然语言继续查询；每个结果都保留数据和 SQL 依据。</p>
    </div>
    """,
    unsafe_allow_html=True,
)

render_executive_brief(current_db)

st.divider()
st.subheader("零售运营 Agent 工作台")
st.caption(
    f"受控演示：订单状态、库存和退货政策由公开销售数据确定性生成，演示日期为 {DEMO_TODAY.isoformat()}。"
    "读操作自动执行；创建退货申请必须人工确认，且只写入独立演示库。"
)

agent_example_cols = st.columns(len(AGENT_EXAMPLES))
for container, example in zip(agent_example_cols, AGENT_EXAMPLES):
    container.button(
        example,
        width="stretch",
        key=f"agent_example_{example}",
        on_click=set_agent_query,
        args=(example, False),
    )

agent_query = st.text_input(
    "输入运营任务",
    key="agent_query",
    placeholder="例如：订单 T0000064 想退货，原因是尺寸不合适",
)
agent_run_clicked = st.button("运行 Agent", type="primary", key="run_agent")
agent_run_clicked = agent_run_clicked or st.session_state.pop("agent_auto_run", False)
current_action_db = action_db_path(current_db)

if agent_run_clicked:
    if not agent_query.strip():
        st.warning("请先输入订单、库存或退货相关任务。")
    elif len(agent_query) > MAX_QUESTION_LENGTH:
        st.error("任务过长，请控制在 300 个字符以内。")
    else:
        try:
            with st.spinner("正在选择工具并执行受控工作流..."):
                st.session_state.agent_result = run_ops_agent(
                    agent_query,
                    db_path=current_db,
                    action_db_path=current_action_db,
                    session_id=st.session_state.agent_session_id,
                )
                st.session_state.agent_execution = None
        except (ValueError, RuntimeError, sqlite3.Error) as exc:
            st.error(str(exc))

if st.session_state.agent_result:
    render_agent_result(st.session_state.agent_result, current_action_db)

st.divider()
st.subheader("自然语言分析")
st.caption("当前支持销售额、订单数、客单价、折扣、品类、渠道、地区和用户分群。")

example_cols = st.columns(len(EXAMPLE_QUESTIONS))
for container, example in zip(example_cols, EXAMPLE_QUESTIONS):
    container.button(
        example,
        width="stretch",
        key=f"example_{example}",
        on_click=set_question,
        args=(example, False),
    )

question = st.text_input(
    "输入业务问题",
    key="question",
    placeholder="例如：哪个品类销售额最高？",
)
run_clicked = st.button("生成分析", type="primary", width="content")
run_clicked = run_clicked or st.session_state.pop("auto_run", False)

if run_clicked and not question.strip():
    st.warning("请先输入一个业务问题。")

if run_clicked and question.strip():
    if len(question) > MAX_QUESTION_LENGTH:
        st.error("问题过长，请控制在 300 个字符以内。")
    elif has_risky_intent(question):
        st.error("检测到删除、修改或建表等危险意图，已拒绝执行。")
        st.info("当前 Demo 只支持只读数据分析问题。")
    else:
        try:
            with st.spinner("正在生成查询并分析结果..."):
                diagnostic = diagnose_channel_performance(question, current_db)
                if diagnostic:
                    result = diagnostic["result"]
                    analysis_result = {**diagnostic, "db_path": current_db}
                else:
                    raw_sql = ask_llm(build_sql_prompt(question))
                    sql = clean_sql(raw_sql)
                    if not is_safe_sql(sql):
                        raise ValueError("模型生成的 SQL 未通过只读安全校验，已拒绝执行。")
                    result = run_sql(sql, current_db)
                    if result.empty or result.isna().all(axis=None):
                        raise ValueError("没有匹配结果，请检查日期、品类或渠道名称。")
                    if len(result) > MAX_RESULT_ROWS:
                        result = result.head(MAX_RESULT_ROWS)
                    explanation = summarize_result(question, result)
                    analysis_result = {
                        "question": question,
                        "sql": sql,
                        "result": result,
                        "explanation": explanation,
                        "db_path": current_db,
                    }

            st.session_state.analysis = analysis_result
            st.session_state.history.insert(0, {"question": question, "rows": len(result)})
            st.session_state.history = st.session_state.history[:5]
        except (ValueError, RuntimeError) as exc:
            st.error(str(exc))

analysis = st.session_state.analysis
if analysis and analysis.get("db_path") == current_db:
    render_analysis(analysis)

if st.session_state.history:
    with st.expander("最近查询（当前会话）"):
        for item in st.session_state.history:
            st.write(f"{item['question']} - 返回 {item['rows']} 行")

st.caption(
    "能力边界：经营分析仍不包含真实库存、成本、利润、退货和商品评价；"
    "运营工作台使用明确标记的合成演示数据，不连接真实订单系统，也不会自动退款。"
)
