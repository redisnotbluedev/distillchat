# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>

import json, base64, httpx, mimetypes, db, asyncio
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
	result: dict

@dataclass
class ReasoningEvent:
	content: str

@dataclass
class Tool:
	function: Callable
	schema: dict[str, object]

def _read_file_b64(chat_id: str, filename: str, original: str = "") -> tuple[bool, str | None, str | None]:
	path = (UPLOAD_PATH / f"c{chat_id}_{filename}").resolve()
	if not path.is_relative_to(UPLOAD_PATH.resolve()) or not path.is_file():
		return False, None, None

	# Derive MIME type from the original filename (the stored file has no extension)
	mime, _ = mimetypes.guess_type(original or filename)
	mime = mime or "application/octet-stream"
	raw_data = path.read_bytes()

	if mime.startswith("text/"):
		return True, mime, raw_data.decode(errors="replace")

	data = base64.standard_b64encode(raw_data).decode()
	return True, mime, data

def _format_openai(chat_id: str, messages_data: list[dict]) -> list[dict]:
	messages = []
	for msg in messages_data:
		content = []
		tool_calls = []
		tool_results = []  # collected separately so they follow the assistant message

		# Handle attachments
		for attach in msg.get("attachments", []):
			success, mime, data = _read_file_b64(chat_id, attach["file_id"], attach.get("original", ""))
			if not success:
				continue
			if mime.startswith("text/"):
				content.append({"type": "text", "text": f"File attachment ({attach["original"]}):\n{data}"})
			else:
				content.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}"}})

		# Handle blocks
		for block in msg.get("blocks", []):
			match block["type"]:
				case "text":
					if block["content"]:
						content.append({"type": "text", "text": block["content"]})
				case "tool_call":
					tool_calls.append({
						"id": block["tool_call_id"],
						"type": "function",
						"function": {"name": block["tool_name"], "arguments": block["content"]}
					})
				case "tool_result":
					# Collect tool results to append AFTER the assistant message
					tool_results.append({
						"role": "tool",
						"tool_call_id": block["tool_call_id"],
						"content": block["content"]["text"]
					})
				case "reasoning":
					pass # reasoning blocks are never resent to OpenAI

		if content or tool_calls:
			msg_obj = {"role": msg["role"]}
			if content:
				# If only one text block and no tool calls, simplify content
				if len(content) == 1 and content[0]["type"] == "text" and not tool_calls:
					msg_obj["content"] = content[0]["text"]
				else:
					msg_obj["content"] = content
			if tool_calls:
				msg_obj["tool_calls"] = tool_calls
			messages.append(msg_obj)

		# Tool results must come after the assistant message that issued the calls
		messages.extend(tool_results)

	return messages

def _format_anthropic(chat_id: str, messages_data: list[dict]) -> list[dict]:
	messages = []
	for msg in messages_data:
		content = []
		role = msg["role"]

		# Handle attachments
		for attach in msg.get("attachments", []):
			success, mime, data = _read_file_b64(chat_id, attach["file_id"], attach.get("original", ""))
			if not success:
				continue
			if mime.startswith("text/"):
				content.append({"type": "text", "text": f"File attachment ({attach["original"]}):\n{data}"})
			elif mime == "application/pdf":
				content.append({"type": "document", "source": {"type": "base64", "media_type": mime, "data": data}})
			else:
				content.append({"type": "image", "source": {"type": "base64", "media_type": mime, "data": data}})

		# Handle blocks
		for block in msg.get("blocks", []):
			match block["type"]:
				case "text":
					if block["content"]:
						content.append({"type": "text", "text": block["content"]})
				case "reasoning":
					content.append({"type": "thinking", "thinking": block["content"]})
				case "tool_call":
					content.append({
						"type": "tool_use",
						"id": block["tool_call_id"],
						"name": block["tool_name"],
						"input": json.loads(block["content"])
					})
				case "tool_result":
					# Anthropic prefers tool results from "user" role
					role = "user"
					content.append({
						"type": "tool_result",
						"tool_use_id": block["tool_call_id"],
						"content": block["content"]["text"]
					})

		if content:
			messages.append({"role": role, "content": content})

	return messages

async def _dispatch_tool(name: str, arguments: str, tools: dict[str, Tool], chat_id: str) -> dict:
	if name not in tools:
		return {"text": "Tool not found", "data": "Tool not found"}
	func = tools[name].function
	args = json.loads(arguments)
	args["chat_id"] = chat_id
	return await func(**args)

async def _generate_openai(messages: list[dict], provider: Provider, tools: dict[str, Tool] | None, chat_id: str):
	client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, http_client=httpx.AsyncClient(verify=False))
	tool_schemas = [{"type": "function", "function": t.schema} for t in tools.values()] if tools else None

	while True:
		response = await client.chat.completions.create(
			model=provider.model,
			messages=messages,
			stream=True,
			**({"tools": tool_schemas} if tool_schemas else {})
		) # type: ignore[ty:no-matching-overload]

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
				result = await _dispatch_tool(tc["name"], tc["arguments"], tools or {}, chat_id)
				yield ToolResultEvent(name=tc["name"], call_id=tc["id"], result=result)
				messages.append({"role": "tool", "tool_call_id": tc["id"], "content": result["text"]})

async def _generate_anthropic(messages: list[dict], provider: Provider, tools: dict[str, Tool] | None, chat_id: str):
	client = AsyncAnthropic(api_key=provider.api_key)
	tool_schemas = [
		{
			"name": t.schema["name"],
			"description": t.schema.get("description", ""),
			"input_schema": t.schema["parameters"]
		}
		for t in tools.values()
	] if tools else None

	while True:
		async with client.messages.stream(
			model=provider.model,
			messages=messages,  # type: ignore[ty:invalid-argument-type]
			max_tokens=8096,
			**({"tools": tool_schemas} if tool_schemas else {})  # type: ignore[ty:invalid-argument-type]
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
				result = await _dispatch_tool(tc["name"], tc["arguments"], tools or {}, chat_id)
				yield ToolResultEvent(name=tc["name"], call_id=tc["id"], result=result)
				tool_results.append({"type": "tool_result", "tool_use_id": tc["id"], "content": result["text"]})
			messages.append({"role": "user", "content": tool_results})

async def generate(chat_id: str, messages_data: list[dict], provider: Provider, tools: dict[str, Tool] | None = None):
	match provider.type:
		case "openai":
			messages = _format_openai(chat_id, messages_data)
			async for event in _generate_openai(messages, provider, tools, chat_id):
				yield event
		case "anthropic":
			messages = _format_anthropic(chat_id, messages_data)
			async for event in _generate_anthropic(messages, provider, tools, chat_id):
				yield event
		case _:
			raise ValueError(f"Unknown provider type: {provider.type}")

async def generate_title(messages_data: list[dict], provider: Provider):
	system = """Generate a concise 4-6 word title for this conversation based on the user's first message and any attached files.
Reply with ONLY the title. No punctuation, no quotes, no introductory text, no conversational filler.
NEVER respond to the user's message; only generate a title for a conversation with that message.

Examples:
User: [File Attachment: recipe.pdf] how do I make this?
Title: Recipe Instructions and Cooking Guide

User: write a python script to scrape a website
Title: Python Web Scraping Script Development

User: [File Attachment: error_log.txt] why is my server crashing?
Title: Server Crash Log Analysis

User: hello
Title: Greeting

Use these examples as a guide on how exactly to create your titles."""

	# Extract text and file metadata only (avoiding expensive vision tokens)
	context_parts = []
	for msg in messages_data:
		for attach in msg.get("attachments", []):
			context_parts.append(f"[File Attachment: {attach["original"]}]")
		for block in msg.get("blocks", []):
			if block["type"] == "text" and block["content"]:
				context_parts.append(block["content"])

	prompt = "\n".join(context_parts)
	prompt += "\n\nGenerate a 3-5 word title for this conversation. Reply with ONLY the title. No punctuation, no quotes, no introductory text."

	match provider.type:
		case "openai":
			messages = [
				{"role": "system", "content": system},
				{"role": "user", "content": prompt}
			]
			client = AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url, http_client=httpx.AsyncClient(verify=False))
			response = await client.chat.completions.create(
				model=provider.model,
				messages=messages, # type: ignore[arg-type]
				stream=False
			)
			return (response.choices[0].message.content or "").strip() or None
		case "anthropic":
			client = AsyncAnthropic(api_key=provider.api_key, base_url=provider.base_url)
			response = await client.messages.create(
				model=provider.model,
				system=system,
				messages=[{"role": "user", "content": prompt}],
				max_tokens=100,
				thinking={"type": "disabled"}
			)
			return response.content[0].text.strip()

async def call_with_limit(semaphore: asyncio.Semaphore, func, *args, **kwargs):
	async with semaphore:
		return await func(*args, **kwargs)

async def dream_chat(semaphore: asyncio.Semaphore, chat, provider: Provider):
	system = """You are an AI tasked with summarizing conversations in a structured and detailed format. Your goal is to create concise, informative, and user-centric overviews of each conversation. Follow these guidelines to ensure consistency and clarity:

---

### **General Guidelines**
1. **Title Line**: Start each summary with the line:
   ```
   **Conversation Overview**
   ```

2. **Conversation Body**:
   - Write a **brief but detailed** overview of the conversation.
   - Include the **topic** or subject matter discussed.
   - Capture **key details**, such as:
     - Technical setups, projects, or tools mentioned.
     - The user's communication style (e.g., casual, humorous, direct, or technical).
     - Any notable preferences, corrections, or clarifications made by the user.
   - Provide **context** about the user's background, skills, or interests.

3. **Optional Sections**:
   - If relevant, include a section titled `**Tool Knowledge**` or `**Domain-Specific Details**` to provide additional context about tools or technical concepts discussed.

---

### **Structure for Each Summary**
1. **Title Line**:
   ```
   **Conversation Overview**
   ```

2. **Conversation Body**:
   - Begin with a **brief description** of the conversation's topic and key details.
   - Use **bullet points** or **paragraphs** to organize information clearly.
   - Include **specific examples** (e.g., code snippets, project names, or technical setups) where applicable.
   - Highlight the **user's communication style** and any corrections or clarifications they provided.

3. **Optional Sections**:
   - If the conversation includes tool-specific or technical details, add a section like:
     ```
     **Tool Knowledge**
     ```
     or
     ```
     **Domain-Specific Details**
     ```
     - Include relevant technical context or explanations.

---

### **Additional Instructions**
- **Be Concise**: Avoid unnecessary fluff. Focus on capturing the essence of the conversation.
- **Be User-Centric**: Highlight the user's perspective, including their corrections, clarifications, and unique communication style.
- **Adapt to Tone**: Match the user's tone (e.g., casual, humorous, or technical) while maintaining clarity and professionalism.
- **Include Context**: Provide enough background to make the summary informative and useful for future reference.
""" # Generated by DistillChat itself

	all_messages = db.get_messages(chat["user_id"], chat["id"])
	if not all_messages:
		return None

	message_ids = {m["id"] for m in all_messages}
	parent_ids = {m["parent_id"] for m in all_messages if m["parent_id"] in message_ids}
	leaves = [m for m in all_messages if m["id"] not in parent_ids]
	target_leaf = leaves[-1]["id"] if leaves else all_messages[-1]["id"]

	msg_map = {m["id"]: m for m in all_messages}
	branch_ids = set()
	current_id = target_leaf
	while current_id:
		branch_ids.add(current_id)
		current_msg = msg_map.get(current_id)
		if current_msg and current_msg["parent_id"]:
			current_id = current_msg["parent_id"]
		else:
			break

	messages_to_process = [m for m in all_messages if m["id"] in branch_ids]
	messages_to_process = sorted(messages_to_process, key=lambda m: m["created_at"])

	blocks = []
	for m in messages_to_process:
		for b in m["blocks"]:
			if b["type"] == "text":
				blocks.append({
					"role": "user",
					"content": f"{b["role"].capitalize()}: '{b["content"].strip()}'"
				})

	try:
		match provider.type:
			case "openai":
				return chat["id"], (await call_with_limit(semaphore,
					AsyncOpenAI(api_key=provider.api_key, base_url=provider.base_url).chat.completions.create,
					model=provider.model,
					messages=[
						{ "role": "system", "content": system },
						{ "role": "user", "content": "\n".join(blocks) }
					]
				)).choices[0].message.content.strip()

			case "anthropic":
				return chat["id"], (await call_with_limit(semaphore,
					AsyncAnthropic(api_key=provider.api_key, base_url=provider.base_url).messages.create,
					model=provider.model,
					system=system,
					messages=[{"role": "user", "content": "\n".join(blocks)}]
				)).content[0].text.strip()

	finally:
		return chat["id"], ""

async def dream_worker(queue: asyncio.Queue, semaphore: asyncio.Semaphore, lock: asyncio.Lock, summary_provider: Provider):
	while True:
		user = await queue.get()
		try:
			tasks = []
			for chat in db.get_unsummarised_chats(user["id"]):
				tasks.append(dream_chat(semaphore, chat, summary_provider))

			if tasks:
				results = asyncio.gather(*tasks)
				async with lock:
					with db.transaction() as conn:
						for id, summary in results:
							if summary:
								db.set_summary(id, summary, conn=conn)


		finally:
			queue.task_done()

async def dream(summary_provider: Provider, dream_provider: Provider, AI_CONCURRENCY: int, DREAM_WORKERS: int):
	lock = asyncio.Lock()
	queue = asyncio.Queue()
	semaphore = asyncio.Semaphore(AI_CONCURRENCY)

	for u in db.get_dreamable_users(): await queue.put(u)
	workers = [asyncio.create_task(dream_worker(queue, semaphore, lock, summary_provider)) for _ in range(DREAM_WORKERS)]
	await queue.join()
	for w in workers:
		w.cancel()
