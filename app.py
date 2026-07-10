import pandas as pd
import plotly.express as px
import streamlit as st

from src.db import run_sql
from src.evaluator import has_risky_intent, is_safe_sql
from src.llm import ask_llm
from src.prompts import build_sql_prompt


EXAMPLE_QUESTIONS = [
    "哪个品类销售额最高？",
    "不同销售渠道的销售额分别是多少？",
    "2025 年每个月销售额趋势如何？",
    "VIP 用户的客单价是多少？",
]


st.set_page_config(page_title="AI 零售数据问答助手", layout="wide")


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
st.caption("Text-to-SQL / SQLite / Streamlit | 数据集：retail_sales_dataset.csv")

overview = load_overview()
metric_cols = st.columns(4)
metric_cols[0].metric("销售明细行数", overview["total_rows"])
metric_cols[1].metric("总销售额", overview["total_sales"])
metric_cols[2].metric("商品数", overview["product_count"])
metric_cols[3].metric("日期范围", overview["date_range"])

st.divider()

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
    if has_risky_intent(question):
        st.error("检测到删除、修改或建表等危险意图，已拒绝执行。")
        st.info("当前 Demo 只支持只读数据分析问题，例如销售额、订单数、趋势、品类和渠道对比。")
    else:
        with st.spinner("正在生成 SQL 并查询数据..."):
            sql = ask_llm(build_sql_prompt(question)).strip()

        left, right = st.columns([1, 1])
        with left:
            st.subheader("生成的 SQL")
            st.code(sql, language="sql")

        if not is_safe_sql(sql):
            with right:
                st.subheader("安全校验")
                st.error("SQL 未通过只读安全校验，已拒绝执行。")
                st.write("只允许 SELECT 或只读 WITH 查询，禁止修改数据库。")
        else:
            result = run_sql(sql)
            with right:
                st.subheader("安全校验")
                st.success("SQL 已通过只读安全校验。")
                st.write(f"查询返回 {len(result)} 行。")

            tab_result, tab_chart, tab_explain = st.tabs(["查询结果", "可视化", "业务解释"])
            with tab_result:
                st.dataframe(result, use_container_width=True)
            with tab_chart:
                draw_chart(result)
            with tab_explain:
                with st.spinner("正在生成业务解释..."):
                    explanation = explain_result(question, result)
                st.write(explanation)
