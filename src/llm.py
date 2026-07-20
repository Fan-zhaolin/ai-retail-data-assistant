import os

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv()


def build_client() -> OpenAI:
    api_key = os.getenv("LLM_API_KEY")
    if not api_key:
        raise RuntimeError(
            "当前环境未配置 LLM_API_KEY，经营简报和运营 Agent 仍可使用，"
            "自然语言问数需要先配置大模型服务。"
        )
    return OpenAI(api_key=api_key, base_url=os.getenv("LLM_BASE_URL") or None)


def ask_llm(prompt: str) -> str:
    model = os.getenv("LLM_MODEL")
    if not model:
        raise RuntimeError(
            "当前环境未配置 LLM_MODEL，经营简报和运营 Agent 仍可使用，"
            "自然语言问数需要先配置模型名称。"
        )

    response = build_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0,
    )
    return response.choices[0].message.content.strip()
