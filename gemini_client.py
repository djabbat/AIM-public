"""
Google Gemini API client — gemini-2.0-flash (free tier)
1.5M tokens/day, 15 req/min
Uses new google.genai SDK (google-genai package)
"""
import os
from google import genai
from google.genai import types

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = "gemini-2.0-flash"

client = genai.Client(api_key=GEMINI_API_KEY)


def ask(prompt: str, system: str = "", max_tokens: int = 2048) -> str:
    config = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=0.7,
        system_instruction=system if system else None,
    )
    response = client.models.generate_content(
        model=MODEL,
        contents=prompt,
        config=config,
    )
    return response.text


def ask_stream(prompt: str, system: str = "", max_tokens: int = 2048):
    config = types.GenerateContentConfig(
        max_output_tokens=max_tokens,
        temperature=0.7,
        system_instruction=system if system else None,
    )
    for chunk in client.models.generate_content_stream(
        model=MODEL,
        contents=prompt,
        config=config,
    ):
        if chunk.text:
            yield chunk.text


if __name__ == "__main__":
    print("Testing Gemini 2.0 Flash...")
    result = ask("Say hello in 5 languages in one line.")
    print(result)
