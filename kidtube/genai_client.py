"""Shared Google GenAI client for all Gemini-family providers."""
from functools import lru_cache

from .config import env


@lru_cache(maxsize=1)
def get_client():
    from google import genai

    return genai.Client(api_key=env("GEMINI_API_KEY", required=True))
