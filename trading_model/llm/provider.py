"""
LLM provider abstraction. Strategy code asks for text; this module decides
which model gets called.

Default provider is Ollama because a quant repo should be runnable on a train
with no API keys and no surprise invoice.
"""

from __future__ import annotations

import os


SUPPORTED_PROVIDERS = ("ollama", "claude", "openai", "gemini", "groq")


def get_llm_response(prompt: str, system: str | None = None) -> str:
    """Return a text completion from the configured LLM provider."""
    provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower()

    if provider in {"claude", "anthropic"}:
        return _call_anthropic(prompt, system)
    if provider == "openai":
        return _call_openai(prompt, system)
    if provider == "gemini":
        return _call_gemini(prompt, system)
    if provider == "groq":
        return _call_groq(prompt, system)
    if provider == "ollama":
        return _call_ollama(prompt, system)

    choices = ", ".join(SUPPORTED_PROVIDERS)
    raise ValueError(f"Unknown LLM_PROVIDER={provider!r}. Choose one of: {choices}")


def _env_required(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise RuntimeError(f"{name} is required for the selected LLM_PROVIDER")
    return value


def _messages(prompt: str, system: str | None) -> list[dict[str, str]]:
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return messages


def _call_anthropic(prompt: str, system: str | None) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=_env_required("ANTHROPIC_API_KEY"))
    kwargs = {
        "model": os.getenv("ANTHROPIC_MODEL", "claude-opus-4-6"),
        "max_tokens": int(os.getenv("LLM_MAX_TOKENS", "1024")),
        "messages": [{"role": "user", "content": prompt}],
    }
    if system:
        kwargs["system"] = system
    response = client.messages.create(**kwargs)
    return response.content[0].text


def _call_openai(prompt: str, system: str | None) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=_env_required("OPENAI_API_KEY"))
    response = client.chat.completions.create(
        model=os.getenv("OPENAI_MODEL", "gpt-4o"),
        messages=_messages(prompt, system),
    )
    return response.choices[0].message.content or ""


def _call_gemini(prompt: str, system: str | None) -> str:
    import google.generativeai as genai

    genai.configure(api_key=_env_required("GEMINI_API_KEY"))
    model = genai.GenerativeModel(os.getenv("GEMINI_MODEL", "gemini-2.0-flash"))
    full_prompt = f"{system}\n\n{prompt}" if system else prompt
    return model.generate_content(full_prompt).text


def _call_groq(prompt: str, system: str | None) -> str:
    from groq import Groq

    client = Groq(api_key=_env_required("GROQ_API_KEY"))
    response = client.chat.completions.create(
        model=os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
        messages=_messages(prompt, system),
    )
    return response.choices[0].message.content or ""


def _call_ollama(prompt: str, system: str | None) -> str:
    """
    Ollama runs locally: no API key, no cost, no data leaving the machine.
    Install from https://ollama.ai and run: ollama pull llama3.2
    """
    import requests

    payload = {
        "model": os.getenv("OLLAMA_MODEL", "llama3.2"),
        "prompt": f"{system}\n\n{prompt}" if system else prompt,
        "stream": False,
    }
    host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")
    resp = requests.post(f"{host}/api/generate", json=payload, timeout=60)
    resp.raise_for_status()
    return resp.json()["response"]
