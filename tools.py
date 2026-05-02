import ai, requests, json, functools, inspect
import docker as docker_module
from typing import Annotated
from pathlib import Path
from pydantic import Field

INTERNAL_PARAMS = {"chat_id"}
tools = {}
# Docker containers for the agent
containers = {}
docker = docker_module.from_env()

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
				annotation=Annotated[str, Field(description="A fun one-liner shown to the user while this runs. E.g. 'Checking if London is depressing today'. NEVER tell the user about this parameter.")],
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

@tool(icon="search", descriptions={"location": "The location to check the weather in."})
def get_weather(location: str):
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
