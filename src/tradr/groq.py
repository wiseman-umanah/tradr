from __future__ import annotations

import os
import pickle
import re
from pathlib import Path

from groq import AuthenticationError, Groq
from platformdirs import user_config_dir

_client: Groq | None = None

CONFIG_DIR = Path(user_config_dir(appname="tradr", appauthor="wiseman-umanah", ensure_exists=True))
CONFIG_FILE = CONFIG_DIR / "groq_api.pkl"
KEY_PATTERN = re.compile(r"^gsk_[a-zA-Z0-9]{52}$")


def _config_exists() -> bool:
    return CONFIG_FILE.exists()


def _test_api_key(api_key: str) -> tuple[bool, str]:
    """Validate key format and verify against Groq."""
    if not api_key or not api_key.strip():
        return False, "API key cannot be empty."
    api_key = api_key.strip()
    if not api_key.startswith("gsk_"):
        return False, "Invalid key. Groq API keys start with 'gsk_'."
    if len(api_key) != 56:
        return False, f"Invalid key length. Expected 56 characters, got {len(api_key)}."
    if not KEY_PATTERN.match(api_key):
        return False, "Invalid key format. Key contains unexpected characters."
    try:
        client = Groq(api_key=api_key)
        client.models.list()
        return True, "API key is valid."
    except AuthenticationError:
        return False, "API key is invalid. Please check and try again."
    except Exception as exc:
        return False, f"Could not connect to Groq: {exc}"


def save_api_key(api_key: str) -> None:
    """Persist a verified API key to the local config."""
    valid, message = _test_api_key(api_key)
    if not valid:
        raise ValueError(message)
    with CONFIG_FILE.open("wb") as file:
        pickle.dump({"key": api_key.strip()}, file, protocol=pickle.HIGHEST_PROTOCOL)


def _load_cached_key() -> str | None:
    if not _config_exists():
        return None
    try:
        with CONFIG_FILE.open("rb") as file:
            data = pickle.load(file)
            return data.get("key")
    except Exception:
        return None


def get_api_key() -> str:
    """Resolve the API key from env or cache and ensure it's valid."""
    env_key = os.getenv("GROQ_API_KEY")
    if env_key:
        valid, message = _test_api_key(env_key)
        if not valid:
            raise ValueError(message)
        return env_key.strip()

    cached = _load_cached_key()
    if cached:
        valid, message = _test_api_key(cached)
        if not valid:
            raise ValueError(message)
        return cached

    raise FileNotFoundError(
        "No Groq API key found. Set GROQ_API_KEY or call tradr.groq.save_api_key()."
    )


def init_client(api_key: str | None = None) -> None:
    """Initialise the Groq client from the provided or cached key."""
    key = api_key or get_api_key()
    global _client
    _client = Groq(api_key=key)


def get_client() -> Groq:
    if _client is None:
        raise RuntimeError("Groq client not initialized. Call init_client() first.")
    return _client


def load_prompt(context: str, question: str) -> str:
    prompt_path = Path(__file__).with_name("prompt.txt")
    base_prompt = prompt_path.read_text(encoding="utf-8")
    prompt = f"""{base_prompt}
CONTEXT:
{context}

QUESTION:
{question}
"""
    return prompt


def answer_question(prompt: str) -> str:
    client = get_client()
    response = client.chat.completions.create(
        model="openai/gpt-oss-120b",
        messages=[{"role": "system", "content": prompt}],
    )
    return response.choices[0].message.content
