import os
from dotenv import load_dotenv
from openai import OpenAI
load_dotenv()
client = OpenAI(
 api_key=os.getenv("LLM_API_KEY"),
 base_url=os.getenv("LLM_BASE_URL"),
)
def ask_llm(prompt: str) -> str:
 response = client.chat.completions.create(
 model=os.getenv("LLM_MODEL"),
 messages=[{"role": "user", "content": prompt}],
 temperature=0,
 )
 return response.choices[0].message.content.strip()