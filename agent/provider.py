import os
from langchain_google_genai import ChatGoogleGenerativeAI

class ProviderUnavailable(Exception):
    pass

def get_model():
    key = os.getenv('GEMINI_API_KEY', '').strip()
    if not key:
        raise ProviderUnavailable('AI is not configured. Add GEMINI_API_KEY to .env and restart. Tasks, analytics, and the manual planner still work.')
    return ChatGoogleGenerativeAI(model=os.getenv('GEMINI_MODEL', 'gemini-2.5-flash'), api_key=key,
        temperature=0, timeout=30, max_retries=1)
