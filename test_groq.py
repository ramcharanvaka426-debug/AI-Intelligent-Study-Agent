import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI


load_dotenv(Path(__file__).resolve().parent / ".env")

api_key = os.getenv("GROQ_API_KEY", "").strip().strip('"').strip("'")
if not api_key:
    print("[AI Error] Groq call failed: Set GROQ_API_KEY in the root .env file.", flush=True)
    raise SystemExit(1)

try:
    client = OpenAI(
        api_key=api_key,
        base_url="https://api.groq.com/openai/v1",
        max_retries=0,
    )
    response = client.chat.completions.create(
        model="openai/gpt-oss-20b",
        messages=[
            {"role": "user", "content": "In one short sentence, explain what a cell is."}
        ],
        max_tokens=100,
    )
    print(response.choices[0].message.content or "(The model returned an empty response.)")
except Exception as error:
    print(f"[AI Error] Groq call failed: {error}", flush=True)
    status_code = getattr(error, "status_code", None)
    if status_code is not None:
        print(f"[AI Error] HTTP status code: {status_code}", flush=True)
    raise SystemExit(1) from error
