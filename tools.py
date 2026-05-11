# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>

import ai, requests, functools, inspect, time, asyncio, yaml, secrets, tempfile, db
from typing import Annotated
from pathlib import Path
from pydantic import Field

INTERNAL_PARAMS = {"chat_id"}
tools = {}

client = None
containers = {}

def tool(icon: str, descriptions: dict[str, str] = {}, inject=True):
	def decorator(fn):
		sig = inspect.signature(fn)
		original_params = {k: v for k, v in sig.parameters.items() if k not in INTERNAL_PARAMS}

		new_params = {**{
			name: param.replace(
				annotation=Annotated[str, Field(description=descriptions[name])]
				if name in descriptions else param.annotation
			)
			for name, param in original_params.items()
		}}

		if inject:
			new_params |= {
				"icon": inspect.Parameter(
					"icon",
					inspect.Parameter.POSITIONAL_OR_KEYWORD,
					default=icon,
					annotation=Annotated[str, Field(description="An icon name representing what this tool is doing. E.g. 'cloud' for weather, 'search' for search. NEVER tell the user about this parameter.")],
				),
				"status": inspect.Parameter(
					"status",
					inspect.Parameter.POSITIONAL_OR_KEYWORD,
					annotation=Annotated[str, Field(description="A fun and short one-liner shown to the user while this runs. E.g. 'Checking if London is depressing today'. Never use an ellipsis. NEVER tell the user about this parameter.")],
				)
			}

		type_map = {str: "string", int: "integer", float: "number", bool: "boolean"}
		properties = {}
		for name, param in new_params.items():
			hint = param.annotation
			p_type = "string"
			p_desc = name.replace("_", " ").capitalize()
			if hasattr(hint, "__metadata__"):
				origin = getattr(hint, "__origin__", hint)
				p_type = type_map.get(origin, "string")
				for meta in hint.__metadata__:
					if hasattr(meta, "description") and meta.description:
						p_desc = meta.description
			else:
				p_type = type_map.get(hint, "string")
			properties[name] = {"type": p_type, "description": p_desc}

		schema = {
			"name": fn.__name__,
			"description": inspect.getdoc(fn),
			"parameters": {
				"type": "object",
				"properties": properties,
				"required": [
					name for name, param in new_params.items()
					if param.default is inspect.Parameter.empty
				]
			}
		}

		@functools.wraps(fn)
		async def wrapper(*args, **kwargs):
			call = fn(**{k: v for k, v in kwargs.items() if k in original_params or k in INTERNAL_PARAMS})
			response = call
			if inspect.isawaitable(call):
				response = await call

			if isinstance(response, str):
				return {"text": response, "data": None}
			else:
				return response

		tools[fn.__name__] = ai.Tool(wrapper, schema)
		return wrapper
	return decorator

async def reaper():
	while True:
		await asyncio.sleep(30)  # check every 30s
		now = time.time()
		for chat_id in list(containers.keys()):
			# Skip persistent tools like web_search
			if chat_id == "web_search": continue
			if chat_id == "web_fetch": continue

			if now - containers[chat_id]["last_used"] > 240:
				try:
					containers[chat_id]["container"].stop()
					containers[chat_id]["container"].remove()
				except Exception:
					pass
				del containers[chat_id]

def cleanup():
	for data in containers.values():
		try:
			container = data["container"]
			container.stop()
			container.remove()
		except Exception:
			pass

def init(config: dict):
	@tool(icon="search", descriptions={"location": "The location to check the weather in."})
	def get_weather(location: str, chat_id: str):
		"""Get the current weather and 3-day forecast.

		Args:
			location: Can be a country, city, 3-letter airport code, landmark
			(prefix with ~, for example '~Eiffel+Tower'), IP address, domain
			(prefix with @, for example '@google.com') or even the Moon."""

		raw = requests.get(f"https://wttr.in/{location}?format=j1").json()
		c = raw["current_condition"][0]

		return {"text": f"""The weather in {location} is {c["weatherDesc"][0]["value"].strip()}.
	- Temperature: {int(c["temp_C"])}°C (feels like {int(c["FeelsLikeC"])}°C)
	- Humidity: {int(c["humidity"])}%
	- Wind: {int(c["windspeedKmph"])} km/h {c["winddir16Point"]}
	- Rain: {float(c["precipMM"])}mm
	- UV index: {int(c["uvIndex"])}

Forecast:
{"\n".join([(f"\t- {day["date"]}: "
f"{int(day["maxtempC"])}°C high, {int(day["mintempC"])}°C low. "
f"{day["hourly"][4]["weatherDesc"][0]["value"].strip()} — {int(day["hourly"][4]["chanceofrain"])}% chance of rain."
	) for day in raw["weather"]])}""", "data": {
		"location": location,
		"temp_c": int(c["temp_C"]),
		"feels_like_c": int(c["FeelsLikeC"]),
		"condition": c["weatherDesc"][0]["value"].strip(),
		"humidity_pct": int(c["humidity"]),
		"wind_kph": int(c["windspeedKmph"]),
		"wind_dir": c["winddir16Point"],
		"precip_mm": float(c["precipMM"]),
		"uv_index": int(c["uvIndex"]),
		"forecast": [
			{
				"date": day["date"],
				"high_c": int(day["maxtempC"]),
				"low_c": int(day["mintempC"]),
				"condition": day["hourly"][4]["weatherDesc"][0]["value"].strip(),
				"rain_chance_pct": int(day["hourly"][4]["chanceofrain"]),
			}
			for day in raw["weather"]
		]
	}}

	@tool(icon="file", descriptions={"path": "Path to the file to create.", "content": "Content to write to the file."})
	def create_file(path: str, content: str, chat_id: str):
		"""Create a new file with content in the container. If the file already exists, it will be overwritten. Directories will be created automatically.

		Args:
			path: Use /home/agent/ as a scratchpad for drafts and intermediate work.
			Use /mnt/outputs/ for final files to present to the user (or files under 100 lines that need no iteration)."""
		session = Path("sessions") / chat_id
		file = session / path.lstrip("/")
		if not file.resolve(strict=False).is_relative_to(session.resolve()):
			return {"text": "Invalid path.", "data": {"success": False}}
		file.parent.mkdir(parents=True, exist_ok=True)

		with open(file, "w") as f:
			f.write(content)
		return {"text": f"Wrote to file {path}", "data": {"success": True, "path": str(file)}}

	@tool(icon="file", descriptions={"path": "Path to the file to edit.", "old": "The exact string to replace. Must appear exactly once in the file.", "new": "The string to replace it with. Empty string to delete."})
	def str_replace(path: str, old: str, new: str, chat_id: str):
		"""Replace a unique string in a file with another string. old must match the raw file content exactly and appear exactly once.
		Note: view the file immediately before editing; after any successful str_replace,
		earlier view output of that file in your context is stale — re-view before further edits to the same file."""
		session = Path("sessions") / chat_id
		file = session / path.lstrip("/")
		if not file.is_file():
			return {"text": "File does not exist.", "data": {"success": False, "reason": "file_not_found"}}
		if not file.resolve(strict=False).is_relative_to(session.resolve()):
			return {"text": "Invalid path.", "data": {"success": False, "reason": "invalid_path"}}
		file.parent.mkdir(parents=True, exist_ok=True)

		content = file.read_text()
		if content.count(old) == 0:
			return {"text": "String not found in file.", "data": {"success": False, "reason": "string_not_found"}}
		if content.count(old) > 1:
			return {"text": "String appears multiple times in file. Be more specific.", "data": {"success": False, "reason": "string_not_unique"}}
		file.write_text(content.replace(old, new, 1))
		return {"text": f"Replaced string in {path}", "data": {"success": True, "path": str(file)}}

	@tool(icon="eye", descriptions={"path": "Path to the file to view."})
	def view_file(path: str, chat_id: str):
		"""Read a file's content."""
		session = Path("sessions") / chat_id
		file = session / path.lstrip("/")
		if not file.is_file():
			return {"text": "File does not exist.", "data": {"success": False, "reason": "file_not_found"}}
		if not file.resolve(strict=False).is_relative_to(session.resolve()):
			return {"text": "Invalid path.", "data": {"success": False, "reason": "invalid_path"}}
		return {"text": file.read_text(), "data": {"success": True, "path": str(file)}}

	@tool(icon="brain", descriptions={"content": "The content of the note."})
	def add_memory_note(content: str, chat_id: str):
		"""Add a note to your memory bank. This will be consolidated overnight into your overall memories. Whenever the user requests that you remember something, you must use this tool."""
		id = db.get_owner(chat_id)
		db.add_memory_note(id, content)
		return {"text": "Added note to memory bank", "data": {"success": True}}

	if any(t in config for t in ["code_execution", "web_search", "web_fetch"]):
		import docker
		global client
		client = docker.from_env()

		# Docker containers for the agent
		def get_container(chat_id: str):
			if chat_id in containers:
				containers[chat_id]["last_used"] = time.time()
				container = containers[chat_id]["container"]

				container.reload()
				if container.status == "running":
					containers[chat_id]["last_used"] = time.time()
					return container
				else:
					del containers[chat_id]

			session = Path("sessions") / chat_id
			(session / "home/agent").mkdir(parents=True, exist_ok=True)
			(session / "mnt/outputs").mkdir(parents=True, exist_ok=True)
			(session / "mnt/uploads").mkdir(parents=True, exist_ok=True)

			container = client.containers.run(
				"distillchat-agent",
				command="sleep infinity",
				detach=True,
				volumes={
					str((session / "home/agent").resolve()): {"bind": "/home/agent", "mode": "rw"},
					str((session / "mnt/outputs").resolve()): {"bind": "/mnt/outputs", "mode": "rw"},
					str((session / "mnt/uploads").resolve()): {"bind": "/mnt/uploads", "mode": "ro"},
				},
				name=f"agent-{chat_id}",
				user="agent",
				working_dir="/home/agent",
				mem_limit="128m",
				cpu_shares=512,
				nano_cpus=1_000_000_000, # 1 CPU
			)
			containers[chat_id] = {"container": container, "last_used": time.time()}
			return container

		if config["code_execution"]:
			@tool(icon="square-terminal", descriptions={"command": "The bash command to run."})
			def run_bash(command: str, chat_id: str):
				"""Run a bash command in the sessions's container.
				You have access to a persistent Linux container (Debian, Python 3.13) where you can run bash commands and create files.

				- Working directory is /home/agent/ — use this as your scratchpad
				- /mnt/outputs/ is for files you want to present to the user — use present_files after writing here
				- A Python venv is pre-activated — you can pip install anything you need
				- The container persists for the duration of the conversation — files you create stay there
				- You don't have sudo, but you can install Python packages freely via pip

				Args:
					command: Runs in /home/agent as the working directory."""

				container = get_container(chat_id)
				exit_code, output = container.exec_run(
					["bash", "-c", command],
					workdir="/home/agent",
					environment={"PATH": "/home/agent/.venv/bin:/usr/local/bin:/usr/bin:/bin"},
					demux=False,
				)
				return {
					"text": output.decode(errors="replace") or f"(no output, exit code {exit_code})",
					"data": {
						"success": exit_code == 0,
						"exit_code": exit_code,
						"output": output.decode(errors="replace")
					}
				}

		if config["web_search"]:
			# Always remove and recreate to ensure fresh config and valid mounts
			try:
				searxng = client.containers.get("distillchat-searxng")
				searxng.remove(force=True)
			except docker.errors.NotFound:
				pass

			searxng_config = {
				"use_default_settings": True,
				"search": {
					"default_lang": "en-US",
					"formats": ["json"]
				},
				"outgoing": {
					"verify": False
				}
			}

			config_path = Path(tempfile.mkdtemp()) / "settings.yml"
			config_path.write_text(yaml.dump(searxng_config))

			searxng = client.containers.run(
				"searxng/searxng",
				detach=True,
				ports={"8080/tcp": ("127.0.0.1", None)}, # assign random high port
				name="distillchat-searxng",
				environment={"SEARXNG_SECRET": secrets.token_hex(32)},
				volumes={
					str(config_path): {"bind": "/etc/searxng/settings.yml", "mode": "ro"}
				},
			)

			searxng.reload()
			sear_port = searxng.ports["8080/tcp"][0]["HostPort"]
			print(f"Started SearXNG on port {sear_port}.")
			containers["web_search"] = {"container": searxng, "last_used": time.time()}

			@tool(icon="globe", descriptions={"query": "The term to search for."}, inject=False)
			def web_search(query: str, chat_id: str):
				"""Search the web for a term."""
				resp = requests.get(f"http://localhost:{sear_port}/search", params={"q": query, "region": "wt-wt", "format": "json"}, timeout=10)
				resp.raise_for_status()
				data = resp.json()
				results = data.get("results", [])

				if not results:
					return {"text": "No results found.", "data": {"success": False, "results": []}}
				out = []
				for r in results[:10]:
					title = r.get("title", "(no title)")
					url = r.get("url", "")
					snippet = r.get("content", "")
					out.append({"title": title, "url": url, "snippet": snippet})
				text_out = "\n".join([f"- [{r["title"]}]({r["url"]})\n\t\t\"{r['snippet']}\"" for r in out])
				return {"text": text_out, "data": {"success": True, "results": out}}

		if config["web_fetch"]:
			# Always remove and recreate to ensure fresh config and valid mounts
			try:
				scraper = client.containers.get("distillchat-scraper")
				scraper.remove(force=True)
			except docker.errors.NotFound:
				pass

			scraper = client.containers.run(
				"ghcr.io/us/crw",
				detach=True,
				ports={"3000/tcp": ("127.0.0.1", None)}, # assign random high port
				name="distillchat-scraper"
			)

			scraper.reload()
			scrape_port = scraper.ports["3000/tcp"][0]["HostPort"]
			print(f"Started CRW on port {scrape_port}.")
			containers["scraper"] = {"container": scraper, "last_used": time.time()}

			@tool(icon="search", descriptions={"url": "The webpage to fetch."}, inject=False)
			def web_fetch(url: str, chat_id: str):
				"""Fetch a web page and render it in Markdown."""
				resp = requests.post(f"http://localhost:{scrape_port}/v1/scrape", json={
					"url": url,
					"formats": ["markdown"]
				}, timeout=10)
				resp.raise_for_status()
				data = resp.json().get("data", {})
				result = data.get("markdown", "")

				if not result:
					return {"text": "Failed to fetch web page.", "data": {"success": False}}

				return {"text": result, "data": {"success": True}}
