"""Small adapter for any OpenAI-compatible local Gemma endpoint."""

from openai import AsyncOpenAI

from ..config import Settings
from ..schemas import Message

SYSTEM_PROMPT = "You are a helpful personal assistant. Answer in the user's language."


class GemmaClient:
    def __init__(self, settings: Settings) -> None:
        self.model = settings.gemma_model
        self.client = AsyncOpenAI(base_url=settings.gemma_base_url, api_key=settings.gemma_api_key)

    async def reply(self, history: list[Message]) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]
        messages.extend({"role": item.role, "content": item.content} for item in history)
        result = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3,
        )
        return result.choices[0].message.content or "응답을 생성하지 못했습니다."

