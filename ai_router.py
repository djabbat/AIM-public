"""
Hybrid AI Router: Groq (70B) → Gemini (1.5 Flash) → Ollama (local)

Priority:
1. Groq  — fastest, smartest, free (30 req/min limit)
2. Gemini — large context, free (1.5M tokens/day)
3. Ollama — offline fallback (local deepseek-r1:7b)
"""
import os
import sys


def _load_env():
    env_path = os.path.expanduser("~/.env")
    if os.path.exists(env_path):
        with open(env_path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, _, val = line.partition("=")
                    os.environ.setdefault(key.strip(), val.strip())


_load_env()


def ask(prompt: str, system: str = "", max_tokens: int = 2048) -> dict:
    """
    Returns: {"text": str, "model": str, "provider": str}
    """
    # 1. Try Groq
    try:
        from groq_client import ask as groq_ask
        text = groq_ask(prompt, system=system, max_tokens=max_tokens)
        return {"text": text, "model": "llama-3.3-70b-versatile", "provider": "groq"}
    except Exception as e:
        print(f"[router] Groq failed: {e}", file=sys.stderr)

    # 2. Try Gemini
    try:
        from gemini_client import ask as gemini_ask
        text = gemini_ask(prompt, system=system, max_tokens=max_tokens)
        return {"text": text, "model": "gemini-2.0-flash", "provider": "gemini"}
    except Exception as e:
        print(f"[router] Gemini failed: {e}", file=sys.stderr)

    # 3. Fallback: Ollama local
    try:
        import subprocess, json
        model = _get_best_ollama_model()
        result = subprocess.run(
            ["ollama", "run", model, prompt],
            capture_output=True, text=True, timeout=120
        )
        if result.returncode == 0:
            return {"text": result.stdout.strip(), "model": model, "provider": "ollama"}
        raise RuntimeError(result.stderr)
    except Exception as e:
        print(f"[router] Ollama failed: {e}", file=sys.stderr)

    return {"text": "All AI providers unavailable.", "model": "none", "provider": "none"}


def _get_best_ollama_model() -> str:
    """Prefer deepseek-r1:7b, fallback to whatever is installed."""
    import subprocess
    try:
        result = subprocess.run(["ollama", "list"], capture_output=True, text=True)
        if "deepseek-r1:7b" in result.stdout:
            return "deepseek-r1:7b"
        # Get first available model
        lines = [l for l in result.stdout.splitlines() if l and not l.startswith("NAME")]
        if lines:
            return lines[0].split()[0]
    except Exception:
        pass
    return "llama3.2"


if __name__ == "__main__":
    prompt = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "What is CDATA theory of aging? Answer in 2 sentences."
    result = ask(prompt)
    print(f"[{result['provider']} / {result['model']}]\n{result['text']}")
