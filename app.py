import pandas as pd
import plotly.express as px
import streamlit as st

from src.db import ensure_database, run_sql
from src.evaluator import clean_sql, has_risky_intent, is_safe_sql
from src.llm import ask_llm
from src.prompts import build_sql_prompt


MAX_QUESTION_LENGTH = 300
MAX_RESULT_ROWS = 1000
EXAMPLE_QUESTIONS = [
    "哪个品类销售额最高？",
    "不同销售渠道的销售额分别是多少？",
    "2025 年每个月销售额趋势如何？",
    "VIP 用户的客单价是多少？",
]

DISPLAY_NAMES = {
    "category": "品类",
    "product_name": "商品名称",
    "brand": "品牌",
    "sales_channel": "销售渠道",
    "region": "地区",
    "month": "月份",
    "net_sales": "净销售额",
    "sales_amount": "净销售额",
    "total_sales": "净销售额",
    "order_count": "订单数",
    "transaction_count": "订单数",
    "avg_order_value": "客单价",
    "avg_discount": "平均折扣",
}



st.set_page_config(page_title="AI 零售数据问答助手", layout="wide")
ensure_database()

@st.cache_data(show_spinner=False)
def load_overview() -> dict[str, str]:
    total_rows = run_sql("SELECT COUNT(*) AS value FROM fact_sales")["value"].iloc[0]
    total_sales = run_sql("SELECT ROUND(SUM(sales_amount), 2) AS value FROM fact_sales")["value"].iloc[0]
    product_count = run_sql("SELECT COUNT(DISTINCT product_id) AS value FROM dim_product")["value"].iloc[0]
    date_range = run_sql(
        "SELECT MIN(transaction_date) AS start_date, MAX(transaction_date) AS end_date FROM fact_sales"
    )
    return {
        "total_rows": f"{int(total_rows):,}",
        "total_sales": f"{float(total_sales) / 10000:.2f} 万",
        "product_count": f"{int(product_count):,}",
        "date_range": f"{date_range['start_date'].iloc[0]} 至 {date_range['end_date'].iloc[0]}",
    }


def draw_chart(result: pd.DataFrame) -> None:
    numeric_cols = result.select_dtypes(include="number").columns.tolist()
    text_cols = [col for col in result.columns if col not in numeric_cols]
    if len(result) == 0 or not numeric_cols or not text_cols:
        st.info("当前结果不适合自动生成图表，可直接查看表格。")
        return

    x_col = text_cols[0]
    y_col = numeric_cols[0]
    chart_data = result.head(30)
    fig = px.bar(chart_data, x=x_col, y=y_col, title=f"{y_col} by {x_col}")
    fig.update_layout(height=420, margin=dict(l=20, r=20, t=50, b=20))
    st.plotly_chart(fig, use_container_width=True)


def explain_result(question: str, result: pd.DataFrame) -> str:
    markdown_result = result.head(20).to_markdown(index=False)
    prompt = f"用户问题：{question}\n查询结果：{markdown_result}\n请用中文给出简短业务解释，控制在 120 字以内。"
    return ask_llm(prompt)


st.title("AI 零售数据问答助手")
st.caption("用自然语言查询零售销售数据，返回可复核的数据明细、图表和业务结论。")

overview = load_overview()
metric_cols = st.columns([1, 1, 0.7, 1.5])
metric_cols[0].metric("订单记录数", overview["total_rows"])
metric_cols[1].metric("总净销售额", overview["total_sales"])
metric_cols[2].metric("商品数", overview["product_count"])
metric_cols[3].metric("日期范围", overview["date_range"])

st.info("当前支持：净销售额、订单数、客单价、折扣、品类、渠道、地区和用户分群。")
st.caption("暂不支持：库存、成本、利润、退货、商品评价和门店实时数据。")

st.divider()

if "history" not in st.session_state:
    st.session_state.history = []

if "question" not in st.session_state:
    st.session_state.question = EXAMPLE_QUESTIONS[0]

st.subheader("提出业务问题")
example_cols = st.columns(len(EXAMPLE_QUESTIONS))
for col, example in zip(example_cols, EXAMPLE_QUESTIONS):
    if col.button(example, use_container_width=True):
        st.session_state.question = example

question = st.text_input(
    "输入自然语言问题",
    key="question",
    placeholder="例如：哪个品类销售额最高？",
)

run_clicked = st.button("生成分析", type="primary", use_container_width=False)

if run_clicked and not question.strip():
    st.warning("请先输入一个业务问题。")

if run_clicked and question.strip(): 
    if len(question) > MAX_QUESTION_LENGTH:
        st.error("问题过长，请控制在 300 个字符以内。")
        st.stop()
    if has_risky_intent(question):
        st.error("检测到删除、修改或建表等危险意图，已拒绝执行。")
        st.info("当前 Demo 只支持只读数据分析问题，例如销售额、订单数、趋势、品类和渠道对比。")
    else:
        with st.spinner("正在生成 SQL 并查询数据..."):
            raw_sql = ask_llm(build_sql_prompt(question))
            sql = clean_sql(raw_sql)

        left, right = st.columns([1, 1])
        with left:
            st.subheader("查询状态")
            st.info("查询方案已生成，SQL 可在下方“技术详情”查看。")

        if not is_safe_sql(sql):
            with right:
                st.subheader("安全校验")
                st.error("SQL 未通过只读安全校验，已拒绝执行。")
                st.write("只允许 SELECT 或只读 WITH 查询，禁止修改数据库。")
        else:
            result = run_sql(sql)
            if result.empty or result.isna().all(axis=None):
                st.warning("没有匹配结果。请检查日期、品类或渠道名称。")
                st.stop()
            if len(result) > MAX_RESULT_ROWS:
                st.warning("结果超过 1000 行，请增加日期或品类筛选条件。")
                result = result.head(MAX_RESULT_ROWS)
                
            st.session_state.history.insert(0, {
                "question": question,
                "rows": len(result),
            })
            st.session_state.history = st.session_state.history[:5]
                
            with right:
                st.subheader("安全校验")
                st.success("SQL 已通过只读安全校验。")
                st.write(f"查询返回 {len(result)} 行。")

            tab_result, tab_chart, tab_explain, tab_tech = st.tabs(
                ["数据明细", "可视化", "业务结论", "技术详情"]
            )
            with tab_result:
                display_result = result.rename(columns=DISPLAY_NAMES)
                st.dataframe(display_result, use_container_width=True, hide_index=True)
            with tab_chart:
                draw_chart(result)
            with tab_explain:
                with st.spinner("正在生成业务解释..."):
                    explanation = explain_result(question, result)
                st.write(explanation)
            with tab_tech:
                st.success("SQL 已通过只读安全校验。")
                st.code(sql, language="sql")
                st.caption(f"本次查询返回 {len(result)} 行。")
if st.session_state.history:
    with st.expander("最近查询（当前会话）"):
        for item in st.session_state.history:
            st.write(f"{item['question']} - 返回 {item['rows']} 行")