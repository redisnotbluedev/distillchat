# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>

import sqlite3, json, base64, httpx
from pathlib import Path
from collections.abc import Callable
from openai import AsyncOpenAI
from anthropic import AsyncAnthropic
from dataclasses import dataclass

UPLOAD_PATH = Path("uploads")

@dataclass
class Provider:
	type: str  # "openai" | "anthropic"
	api_key: str
	model: str
	base_url: str | None = None

@dataclass
class TokenEvent:
	content: str

@dataclass
class ToolStartEvent:
	name: str
	call_id: str
	arguments: str

@dataclass
class ToolResultEvent:
	name: str
	call_id: str
	result: str

@dataclass
class ReasoningEvent:
	content: str

@dataclass
class Tool:
	function: Callable
	schema: dict[str, object]

def _read_file_b64(content: str) -> tuple[str, str]:
	parsed = json.loads(content)
	path = UPLOAD_PATH / parsed["filename"]
	suffix = path.suffix.lower()
	mime_types = {
		".jpg": "image/jpeg", ".jpeg": "image/jpeg",
		".png": "image/png", ".gif": "image/gif",
		".webp": "image/webp", ".pdf": "application/pdf",
	}
	mime = mime_types.get(suffix, "application/octet-stream")
	data = base64.standard_b64encode(path.read_bytes()).decode()
	return mime, data

def _format_openai(rows: list[sqlite3.Row]) -> list[dict]:
	messages = []
	for row in rows:
		match row["type"]:
			case "text":
				messages.append({"role": row["role"], "content": row["content"]})
			case "file":
				mime, data = _read_file_b64(row["content"])
				messages.append({
					"role": row["role"],
					"content": [{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}}]
				})
			case "reasoning":
				pass  # reasoning blocks are never resent to OpenAI
			case "tool_call":
				messages.append({
					"role": "assistant",
					"tool_calls": [{"id": row["tool_call_id"], "type": "function", "function": {"name": row["tool_name"], "arguments": row["content"]}}]
				})
			case "tool_result":
				messages.append({"role": "tool", "tool_call_id": row["tool_call_id"], "content": row["content"]})
	return messages

def _format_anthropic(rows: list[sqlite3.Row]) -> list[dict]:
	messages = []
	for row in rows:
		match row["type"]:
			case "text":
				messages.append({"role": row["role"], "content": [{"type": "text", "text": row["content"]}]})
			case "file":
				mime, data = _read_file_b64(row["content"])
				if mime == "application/pdf":
					block = {"type": "document", "source": {"type": "base64", "media_type": mime, "data": data}}
				else:
					block = {"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}}
				messages.append({"role": row["role"], "content": [block]})
			case "reasoning":
				messages.append({"role": "assistant", "content": [{"type": "thinking", "thinking": row["content"]}]})
			case "tool_call":
				messages.append({
					"role": "assistant",
					"content": [{"type": "tool_use", "id": row["tool_call_id"], "name": row["tool_name"], "input": json.loads(row["content"])}]
				})
			case "tool_result":
				messages.append({
					"role": "user",
					"content": [{"type": "tool_result", "tool_use_id": row["tool_call_id"], "content": row["content"]}]
				})
	return messages

async def _dispatch_tool(name: str, arguments: str, tools: dict[str, Tool]) -> str:
	if name not in tools:
		return "Tool not found"
	return await tools[name].function(**json.loads(arguments))

async def _generate_openai(messages: list[dict], provider: Provider, tools: dict[str, Tool] | None):
	client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, http_client=httpx.AsyncClient(verify=False))
	tool_schemas = [t.schema for t in tools.values()] if tools else None

	while True:
		response = await client.chat.completions.create(
			model=provider.model,
			messages=messages,
			stream=True,
			**({"tools": tool_schemas} if tool_schemas else {})
		)

		tool_calls_buffer = {}
		finish_reason = None
		text_buffer = ""
		in_think = False
		carry = ""

		async for chunk in response:
			if not chunk.choices:
				continue
			delta = chunk.choices[0].delta
			finish_reason = chunk.choices[0].finish_reason

			if hasattr(delta, "reasoning_content") and delta.reasoning_content:
				yield ReasoningEvent(content=delta.reasoning_content)
			elif hasattr(delta, "reasoning") and delta.reasoning:
				yield ReasoningEvent(content=delta.reasoning)

			if delta.content:
				carry += delta.content
				while True:
					if in_think:
						end = carry.find("</think>")
						if end == -1:
							yield ReasoningEvent(content=carry)
							carry = ""
							break
						yield ReasoningEvent(content=carry[:end])
						carry = carry[end + len("</think>"):]
						in_think = False
					else:
						start = carry.find("<think>")
						if start == -1:
							text_buffer += carry
							yield TokenEvent(content=carry)
							carry = ""
							break
						if start > 0:
							text_buffer += carry[:start]
							yield TokenEvent(content=carry[:start])
						carry = carry[start + len("<think>"):]
						in_think = True

			if delta.tool_calls:
				for tc in delta.tool_calls:
					i = tc.index
					if i not in tool_calls_buffer:
						tool_calls_buffer[i] = {"id": tc.id, "name": "", "arguments": ""}
					if tc.function.name:
						tool_calls_buffer[i]["name"] += tc.function.name
					if tc.function.arguments:
						tool_calls_buffer[i]["arguments"] += tc.function.arguments

		if finish_reason == "stop":
			break

		elif finish_reason == "tool_calls":
			tool_calls = list(tool_calls_buffer.values())
			messages.append({
				"role": "assistant",
				"content": text_buffer or None,
				"tool_calls": [
					{"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
					for tc in tool_calls
				]
			})

			for tc in tool_calls:
				yield ToolStartEvent(name=tc["name"], call_id=tc["id"], arguments=tc["arguments"])
				result = await _dispatch_tool(tc["name"], tc["arguments"], tools or {})
				yield ToolResultEvent(name=tc["name"], call_id=tc["id"], result=result)
				messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result})

async def _generate_anthropic(messages: list[dict], provider: Provider, tools: dict[str, Tool] | None):
	client = AsyncAnthropic(api_key=provider.api_key)
	tool_schemas = [t.schema for t in tools.values()] if tools else None

	while True:
		async with client.messages.stream(
			model=provider.model,
			messages=messages,  # type: ignore[arg-type]
			max_tokens=8096,
			**({"tools": tool_schemas} if tool_schemas else {})  # type: ignore[arg-type]
		) as stream:
			tool_calls_buffer = {}
			text_buffer = ""
			stop_reason = None

			async for event in stream:
				match event.type:
					case "content_block_delta":
						match event.delta.type:
							case "text_delta":
								text_buffer += event.delta.text
								yield TokenEvent(content=event.delta.text)
							case "thinking_delta":
								yield ReasoningEvent(content=event.delta.thinking)
							case "input_json_delta":
								tool_calls_buffer.setdefault(event.index, {"id": "", "name": "", "arguments": ""})
								tool_calls_buffer[event.index]["arguments"] += event.delta.partial_json
					case "content_block_start":
						if event.content_block.type == "tool_use":
							tool_calls_buffer[event.index] = {"id": event.content_block.id, "name": event.content_block.name, "arguments": ""}
					case "message_delta":
						stop_reason = event.delta.stop_reason

		if stop_reason == "end_turn":
			break

		elif stop_reason == "tool_use":
			tool_calls = list(tool_calls_buffer.values())
			messages.append({
				"role": "assistant",
				"content": (
					([{"type": "text", "text": text_buffer}] if text_buffer else []) +
					[{"type": "tool_use", "id": tc["id"], "name": tc["name"], "input": json.loads(tc["arguments"])} for tc in tool_calls]
				)
			})

			tool_results = []
			for tc in tool_calls:
				yield ToolStartEvent(name=tc["name"], call_id=tc["id"], arguments=tc["arguments"])
				result = await _dispatch_tool(tc["name"], tc["arguments"], tools or {})
				yield ToolResultEvent(name=tc["name"], call_id=tc["id"], result=result)
				tool_results.append({"type": "tool_result", "tool_use_id": tc["id"], "content": result})
			messages.append({"role": "user", "content": tool_results})

async def generate(rows: list[sqlite3.Row], provider: Provider, tools: dict[str, Tool] | None = None):
	match provider.type:
		case "openai":
			messages = _format_openai(rows)
			async for event in _generate_openai(messages, provider, tools):
				yield event
		case "anthropic":
			messages = _format_anthropic(rows)
			async for event in _generate_anthropic(messages, provider, tools):
				yield event
		case _:
			raise ValueError(f"Unknown provider type: {provider.type}")

async def generate_title(message: str, provider: Provider):
	system = "Generate a concise 4-6 word title for this conversation. Reply with only the title, no punctuation, no quotes."
	match provider.type:
		case "openai":
			client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, http_client=httpx.AsyncClient(verify=False))
			response = await client.chat.completions.create(
				model=provider.model,
				messages=[
					{"role": "system", "content": system},
					{"role": "user", "content": message},
				],
				stream=False
			)
			return (response.choices[0].message.content or "").strip() or None
		case "anthropic":
			client = AsyncAnthropic(api_key=provider.api_key)
			response = await client.messages.create(
				model=provider.model,
				system=system,
				messages=[{"role": "user", "content": message}],
				thinking={"type": "disabled"}
			)
			return response.content[0].text.strip()
