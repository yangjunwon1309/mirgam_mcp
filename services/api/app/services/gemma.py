"""Adapter for the host-native llama.cpp OpenAI-compatible endpoint."""

import copy
import json
import logging
import math
from dataclasses import dataclass
from openai import APIConnectionError, APIStatusError, AsyncOpenAI

from ..config import Settings
from ..schemas import Message


logger = logging.getLogger(__name__)


class ContextWindowError(RuntimeError):
    """Raised when a request still cannot fit after prompt compaction."""


class EmptyModelResponseError(RuntimeError):
    """Raised when the model returns reasoning but no user-facing answer."""


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True)
class Completion:
    content: str | None
    tool_calls: list[ToolCall]
    assistant_message: dict[str, object]


class GemmaClient:
    # Leave extra room for llama.cpp's chat-template and tool-call serialization,
    # which are not included in our conservative text-token estimate.
    CONTEXT_SAFETY_TOKENS = 192

    def __init__(self, settings: Settings) -> None:
        self.model = settings.gemma_model
        self.system_prompt = settings.gemma_system_prompt
        self.temperature = settings.gemma_temperature
        self.context_size = max(512, settings.gemma_context_size)
        self.max_output_tokens = max(64, settings.gemma_max_output_tokens)
        self.enable_thinking = settings.gemma_enable_thinking
        self.client = AsyncOpenAI(base_url=settings.gemma_base_url, api_key=settings.gemma_api_key)

    async def status(self) -> dict[str, object]:
        """Report whether llama.cpp is reachable without generating a response."""
        try:
            models = await self.client.models.list()
        except APIConnectionError:
            return {"reachable": False, "model_available": False}
        except APIStatusError as exc:
            return {"reachable": False, "model_available": False, "status_code": exc.status_code}

        model_ids = [model.id for model in models.data]
        return {
            "reachable": True,
            "model_available": self.model in model_ids,
            "models": model_ids,
        }

    async def complete(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None = None,
        enable_thinking: bool | None = None,
        tool_choice: str | None = None,
        max_tokens: int | None = None,
    ) -> Completion:
        request_messages = copy.deepcopy(messages)
        use_thinking = self.enable_thinking if enable_thinking is None else enable_thinking
        output_limit = max(32, max_tokens) if max_tokens is not None else self.max_output_tokens
        prompt_budget = max(
            128,
            self.context_size - output_limit - self.CONTEXT_SAFETY_TOKENS,
        )
        self._fit_context(request_messages, tools, prompt_budget)
        try:
            result = await self._create_completion(
                request_messages, tools, use_thinking, tool_choice, output_limit
            )
        except APIStatusError as exc:
            if not self._is_context_overflow(exc):
                raise
            # The server's tokenizer is authoritative. If its chat template pushes
            # the request over the limit, compact more aggressively and retry once.
            logger.warning("llama.cpp rejected an oversized prompt; compacting and retrying")
            self._fit_context(request_messages, tools, max(128, prompt_budget * 3 // 4))
            try:
                result = await self._create_completion(
                    request_messages, tools, use_thinking, tool_choice, output_limit
                )
            except APIStatusError as retry_error:
                if self._is_context_overflow(retry_error):
                    raise ContextWindowError(
                        "대화와 도구 결과가 모델 컨텍스트 한도를 초과했습니다. 새 대화를 시작하거나 "
                        "더 짧은 기간의 데이터만 요청해 주세요."
                    ) from retry_error
                raise
        message = result.choices[0].message
        finish_reason = result.choices[0].finish_reason
        reasoning_content = getattr(message, "reasoning_content", None) or ""
        tool_calls: list[ToolCall] = []
        for tool_call in message.tool_calls or []:
            try:
                arguments = json.loads(tool_call.function.arguments or "{}")
            except json.JSONDecodeError:
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            tool_calls.append(
                ToolCall(
                    call_id=tool_call.id,
                    name=tool_call.function.name,
                    arguments=arguments,
                )
            )
        content = message.content.strip() if message.content and message.content.strip() else None
        if not content and not tool_calls:
            logger.warning(
                "Gemma returned no user-facing content (finish_reason=%s, reasoning_chars=%d)",
                finish_reason,
                len(reasoning_content),
            )
        elif finish_reason == "length":
            logger.warning(
                "Gemma reached the output token limit (%d); content_chars=%d reasoning_chars=%d",
                output_limit,
                len(content or ""),
                len(reasoning_content),
            )
        return Completion(
            content=content,
            tool_calls=tool_calls,
            assistant_message=message.model_dump(exclude_none=True),
        )

    async def _create_completion(
        self,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
        enable_thinking: bool,
        tool_choice: str | None,
        max_tokens: int,
    ):
        return await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=self.temperature,
            max_tokens=max_tokens,
            tools=tools or None,
            tool_choice=tool_choice if tool_choice is not None else ("auto" if tools else None),
            extra_body={"chat_template_kwargs": {"enable_thinking": enable_thinking}},
        )

    @staticmethod
    def _estimate_tokens(value: object) -> int:
        """Conservative estimate: CJK chars/punctuation count individually, ASCII in 3-char chunks."""
        text = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        estimated = 0.0
        ascii_run = 0
        for char in text:
            if char.isascii() and char.isalnum():
                ascii_run += 1
                continue
            if ascii_run:
                estimated += math.ceil(ascii_run / 3)
                ascii_run = 0
            if char.isspace():
                estimated += 0.25
            elif char.isascii():
                estimated += 0.8
            else:
                estimated += 1.25
        if ascii_run:
            estimated += math.ceil(ascii_run / 3)
        return math.ceil(estimated)

    @classmethod
    def _request_token_estimate(
        cls, messages: list[dict[str, object]], tools: list[dict[str, object]] | None
    ) -> int:
        # Per-message overhead approximates role and template control tokens.
        return cls._estimate_tokens(messages) + cls._estimate_tokens(tools or []) + 8 * len(messages) + 32

    @classmethod
    def _fit_context(
        cls,
        messages: list[dict[str, object]],
        tools: list[dict[str, object]] | None,
        prompt_budget: int,
    ) -> None:
        """Keep the current turn, prune old turns, then shorten oversized payloads."""
        original_estimate = cls._request_token_estimate(messages, tools)
        while cls._request_token_estimate(messages, tools) > prompt_budget:
            user_indexes = [i for i, message in enumerate(messages) if message.get("role") == "user"]
            latest_user = user_indexes[-1] if user_indexes else len(messages)

            # Stored history is user/assistant pairs. Remove its oldest pair first;
            # never drop the current user request or this turn's tool-call protocol.
            if latest_user > 1:
                remove_count = 2 if latest_user >= 3 else 1
                del messages[1 : 1 + remove_count]
                continue

            # Large MCP payloads are the common cause of sudden context overflow.
            tool_messages = [
                item
                for item in messages[latest_user + 1 :]
                if item.get("role") == "tool" and item.get("content") != "[도구 결과 생략]"
            ]
            largest_tool = max(
                tool_messages,
                key=lambda item: len(str(item.get("content", ""))),
                default=None,
            )
            if largest_tool is not None:
                content = str(largest_tool.get("content", ""))
                if len(content) > 160:
                    keep = max(120, len(content) // 2)
                    head = keep * 3 // 4
                    tail = keep - head
                    largest_tool["content"] = (
                        content[:head]
                        + "\n[… 도구 결과가 컨텍스트 한도에 맞게 생략됨 …]\n"
                        + content[-tail:]
                    )
                else:
                    largest_tool["content"] = "[도구 결과 생략]"
                continue

            # A very long single user input can itself exceed the window.
            if latest_user < len(messages):
                content = str(messages[latest_user].get("content", ""))
                if len(content) > 240:
                    keep = max(160, len(content) // 2)
                    head = keep * 3 // 4
                    tail = keep - head
                    messages[latest_user]["content"] = (
                        content[:head] + "\n[… 입력 일부 생략 …]\n" + content[-tail:]
                    )
                    continue
            break

        final_estimate = cls._request_token_estimate(messages, tools)
        if final_estimate < original_estimate:
            logger.info(
                "Compacted LLM prompt from approximately %d to %d tokens (budget %d)",
                original_estimate,
                final_estimate,
                prompt_budget,
            )

    @staticmethod
    def _is_context_overflow(error: APIStatusError) -> bool:
        detail = str(error).lower()
        response = getattr(error, "response", None)
        if response is not None:
            try:
                detail += response.text.lower()
            except Exception:
                pass
        return "context" in detail and ("exceed" in detail or "token" in detail)

    def conversation_messages(self, history: list[Message], has_tools: bool) -> list[dict[str, object]]:
        prompt = self.system_prompt
        if has_tools:
            prompt += (
                "\n\n현재 정보가 필요한 질문에는 제공된 도구를 사용하세요. "
                "도구 결과 없이 센서값, 카메라 상태, 파일 내용 또는 분석 결과를 지어내지 마세요."
            )
        messages: list[dict[str, object]] = [{"role": "system", "content": prompt}]
        messages.extend({"role": item.role, "content": item.content} for item in history)
        return messages
