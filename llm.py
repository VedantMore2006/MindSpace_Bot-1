"""
LLM configuration - Anthropic Claude only.
"""

from langchain_anthropic import ChatAnthropic
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

# Primary LLM - Anthropic Claude
llm = ChatAnthropic(
    model=ANTHROPIC_MODEL,
    anthropic_api_key=ANTHROPIC_API_KEY,
    temperature=0.3,
    max_tokens=500,
    timeout=60,
)
