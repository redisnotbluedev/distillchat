import ai, requests, json, functools, inspect, time, docker, asyncio
from typing import Annotated
from pathlib import Path
from pydantic import Field

INTERNAL_PARAMS = {"chat_id"}
tools = {}
# Docker containers for the agent
client: docker.client.DockerClient = docker.from_env()
containers = {}

def tool(icon: str, descriptions: dict[str, str] = {}):
	def decorator(fn):
		sig = inspect.signature(fn)
		original_params = {k: v for k, v in sig.parameters.items() if k not in INTERNAL_PARAMS}

		new_params = {
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
			),
			**{
				name: param.replace(
					annotation=Annotated[str, Field(description=descriptions[name])]
					if name in descriptions else param.annotation
				)
				for name, param in original_params.items()
			}
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
			if inspect.isawaitable(call):
				return json.dumps(await call)
			return json.dumps(call)

		tools[fn.__name__] = ai.Tool(wrapper, schema)
		return wrapper
	return decorator

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

async def reaper():
	while True:
		await asyncio.sleep(30)  # check every 30s
		now = time.time()
		for chat_id in list(containers.keys()):
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
			data["container"].stop()
			data["container"].remove()
		except Exception:
			pass

@tool(icon="search", descriptions={"location": "The location to check the weather in."})
def get_weather(location: str, chat_id: str):
	"""Get the current weather and 3-day forecast.

	Args:
		location: Can be a country, city, 3-letter airport code, landmark
		(prefix with ~, for example '~Eiffel+Tower'), IP address, domain
		(prefix with @, for example '@google.com') or even the Moon."""

	raw = requests.get(f"https://wttr.in/{location}?format=j1").json()
	c = raw["current_condition"][0]

	return {
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
	}

@tool(icon="file", descriptions={"path": "Path to the file to create.", "content": "Content to write to the file."})
def create_file(path: str, content: str, chat_id: str):
	"""Create a new file with content in the container. If the file already exists, it will be overwritten. Directories will be created automatically.

	Args:
		path: Use /home/agent/ as a scratchpad for drafts and intermediate work.
		Use /mnt/outputs/ for final files to present to the user (or files under 100 lines that need no iteration)."""
	session = Path("sessions") / chat_id
	file = session / path.lstrip("/")
	if not file.resolve(strict=False).is_relative_to(session.resolve()):
		return {"detail": "Invalid path."}
	file.parent.mkdir(parents=True, exist_ok=True)

	with open(file, "w") as f:
		f.write(content)
	return {"detail": f"Wrote to file {path}"}

@tool(icon="file", descriptions={"path": "Path to the file to edit.", "old": "The exact string to replace. Must appear exactly once in the file.", "new": "The string to replace it with. Empty string to delete."})
def str_replace(path: str, old: str, new: str, chat_id: str):
	"""Replace a unique string in a file with another string. old must match the raw file content exactly and appear exactly once.
	Note: view the file immediately before editing; after any successful str_replace,
	earlier view output of that file in your context is stale — re-view before further edits to the same file."""
	session = Path("sessions") / chat_id
	file = session / path.lstrip("/")
	if not file.is_file():
		return {"detail": "File does not exist."}
	if not file.resolve(strict=False).is_relative_to(session.resolve()):
		return {"detail": "Invalid path."}
	file.parent.mkdir(parents=True, exist_ok=True)

	content = file.read_text()
	if content.count(old) == 0:
		return {"detail": "String not found in file."}
	if content.count(old) > 1:
		return {"detail": "String appears multiple times in file. Be more specific."}
	file.write_text(content.replace(old, new, 1))
	return {"detail": f"Replaced string in {path}"}

@tool(icon="eye", descriptions={"path": "Path to the file to view."})
def view_file(path: str, chat_id: str):
	"""Read a file's content."""
	session = Path("sessions") / chat_id
	file = session / path.lstrip("/")
	if not file.is_file():
		return {"detail": "File does not exist."}
	if not file.resolve(strict=False).is_relative_to(session.resolve()):
		return {"detail": "Invalid path."}
	return {"content": file.read_text()}

@tool(icon="square-terminal", descriptions={"command": "The bash command to run."})
async def run_bash(command: str, chat_id: str):
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
	return output.decode(errors="replace") or f"(no output, exit code {exit_code})"
