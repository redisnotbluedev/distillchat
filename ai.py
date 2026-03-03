import sqlite3, json, os
from openai import AsyncOpenAI
from dataclasses import dataclass

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
class DoneEvent:
	pass

class Client:
	def __init__(self):
		self.client = AsyncOpenAI(
			base_url=os.getenv("OPENAI_BASE_URL"),
			api_key=os.getenv("OPENAI_API_KEY")
		)

	def _format_messages(self, rows: list[sqlite3.Row]) -> list[dict]:
		messages = []
		for row in rows:
			if row["type"] == "text":
				messages.append({"role": row["role"], "content": row["content"]})
			elif row["type"] == "tool_call":
				messages.append({
					"role": "assistant",
					"tool_calls": [{"id": row["tool_call_id"], "type": "function", "function": {"name": row["tool_name"], "arguments": row["content"]}}]
				})
			elif row["type"] == "tool_result":
				messages.append({"role": "tool", "tool_call_id": row["tool_call_id"], "content": row["content"]})
		return messages

	async def dispatch_tool(self, name: str, arguments: str):
		args = json.loads(arguments)
		tools = {}
		if name not in tools:
			return "Tool not found"
		return await tools[name](**args)

	async def generate(self, model, rows):
		messages = self._format_messages(rows)

		while True:
			response = await self.client.chat.completions.create(
				model=model,
				messages=messages,
				stream=True
			)

			tool_calls_buffer = {}
			finish_reason = None
			text_buffer = ""

			async for chunk in response:
				if not chunk.choices:
					continue
				delta = chunk.choices[0].delta
				finish_reason = chunk.choices[0].finish_reason

				if delta.content:
					text_buffer += delta.content
					yield TokenEvent(content=delta.content)

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
				yield DoneEvent()
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
					result = await self.dispatch_tool(tc["name"], tc["arguments"])
					yield ToolResultEvent(name=tc["name"], call_id=tc["id"], result=result)
					messages.append({
						"role": "tool",
						"tool_call_id": tc["id"],
						"content": result
					})
