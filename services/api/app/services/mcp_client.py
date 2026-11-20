"""MCP client used by FastAPI, not by the browser or llama.cpp directly."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MCPTool:
    name: str
    description: str
    input_schema: dict[str, object]
    output_schema: dict[str, object]

    def as_openai_tool(self) -> dict[str, object]:
        description = self.description
        output_properties = self.output_schema.get("properties")
        if isinstance(output_properties, dict) and output_properties:
            fields = ", ".join(str(name) for name in output_properties)
            description = f"{description} Returns JSON fields: {fields}."
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": description,
                "parameters": self.input_schema,
            },
        }


class MCPClient:
    def __init__(self, url: str) -> None:
        self.url = url

    async def list_tools(self) -> list[MCPTool]:
        try:
            async with streamablehttp_client(url=self.url) as (read_stream, write_stream, _):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    response = await session.list_tools()
        except Exception:  # MCP must not make ordinary chat unavailable.
            logger.exception("Unable to discover MCP tools at %s", self.url)
            return []

        tools: list[MCPTool] = []
        for tool in response.tools:
            schema = getattr(tool, "inputSchema", {}) or {}
            tools.append(
                MCPTool(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=dict(schema),
                    output_schema=dict(getattr(tool, "outputSchema", {}) or {}),
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, object]) -> str:
        async with streamablehttp_client(url=self.url) as (read_stream, write_stream, _):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                response = await session.call_tool(name, arguments)

        structured = getattr(response, "structuredContent", None)
        if structured is not None:
            # MCP SDKs wrap primitive tool outputs in {"result": ...} when
            # exposing structuredContent. Unwrap that envelope so callers get
            # the original string (several tools return JSON as a string).
            if isinstance(structured, dict) and set(structured) == {"result"}:
                value = structured["result"]
                result = value if isinstance(value, str) else json.dumps(
                    value, ensure_ascii=False, separators=(",", ":"), default=str
                )
            else:
                result = json.dumps(structured, ensure_ascii=False, separators=(",", ":"), default=str)
            if getattr(response, "isError", False):
                raise RuntimeError(result)
            return result

        content: list[str] = []
        for item in response.content:
            if getattr(item, "type", None) == "text":
                content.append(item.text)
            elif hasattr(item, "model_dump"):
                content.append(json.dumps(item.model_dump(by_alias=True), ensure_ascii=False))
            else:
                content.append(str(item))
        parsed: list[object] = []
        all_json = bool(content)
        for item in content:
            try:
                parsed.append(json.loads(item))
            except json.JSONDecodeError:
                all_json = False
                break
        if all_json:
            value: object = parsed[0] if len(parsed) == 1 else parsed
            result = json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
        else:
            result = "\n".join(content) or "도구가 빈 결과를 반환했습니다."
        if getattr(response, "isError", False):
            raise RuntimeError(result)
        return result
