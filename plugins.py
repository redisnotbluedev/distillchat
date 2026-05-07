# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
# idk why but i decided to make this one short
# Have fun reading this!
import asyncio, importlib.util, sys, collections, inspect, uuid, pathlib
hooks, config = collections.defaultdict(set[collections.abc.Callable]), {}
async def _safe(function: collections.abc.Callable, hook: str, **kwargs):
	try: await result if inspect.isawaitable(result := function(**kwargs)) else result
	except Exception as e: print(f"Error in plugin when calling hook {hook}: {e}")
def _register(type: str, function: collections.abc.Callable): hooks[type].add(function)
async def run(hook: str, **kwargs): await asyncio.gather(*[_safe(h, hook, **kwargs) for h in hooks[hook]])
def load(cfg: dict):
	global config; config = cfg
	root = pathlib.Path(__file__).parent / "plugins"
	for name in cfg.get("plugins", []):
		path = root / f"{name}.py"
		if not path.is_file(): continue
		spec = importlib.util.spec_from_file_location(f"p_{uuid.uuid4().hex}", path)
		if spec:
			mod = importlib.util.module_from_spec(spec)
			if spec.loader:
				try:
					sys.modules[mod.__name__] = mod
					spec.loader.exec_module(mod)
					for h, f in getattr(mod, "HOOKS", {}).items(): _register(h, f)
				except Exception as e: print(f"Error initializing plugin {name}: {e}")
