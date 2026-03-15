"""
Groq API client — llama-3.1-70b-versatile (free tier)
Fast inference, 30 req/min, 6000 tokens/min
"""
import os
from groq import Groq

GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")
MODEL = "llama-3.3-70b-versatile"

client = Groq(api_key=GROQ_API_KEY)


def ask(prompt: str, system: str = "", max_tokens: int = 2048) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.7,
    )
    return response.choices[0].message.content


def ask_stream(prompt: str, system: str = "", max_tokens: int = 2048):
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    stream = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0.7,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta


if __name__ == "__main__":
    print("Testing Groq llama-3.1-70b...")
    result = ask("Say hello in 5 languages in one line.")
    print(result)
