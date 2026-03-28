# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>

import json, logging, mimetypes, re, sys, jwt, pyaml_env, ai, db
from pathlib import Path
from uuid import uuid4
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

def parse_size(size):
	units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
	match = re.match(r"(\d+\.?\d*)\s*([a-zA-Z]?)", str(size).strip())
	if not match:
		return 0
	number, unit = match.groups()
	return int(float(number) * units.get(unit.upper(), 1))

env_path = Path(".env")
if not env_path.exists():
	logger.warning(".env not found — environment variables must be set manually.")
load_dotenv(env_path)

config_path = Path("config.yaml")
if not config_path.exists():
	logger.warning("config.yaml not found — copy config.yaml.example to config.yaml and fill in your values.")
	sys.exit(1)
config = pyaml_env.parse_config(str(config_path))

BRAND_NAME = config["brand"]["brand_name"]
SECRET_KEY = config["general"]["secret_key"]
ICONS = [f.stem for f in Path("templates/icons").glob("*.svg")]

MAX_UPLOAD_SIZE = parse_size(config["general"]["max_upload_size"])
UPLOAD_PATH = Path("./uploads")
UPLOAD_PATH.mkdir(exist_ok=True)

models = config["generation"]["models"]
DEFAULT_MODEL = next(m for m in models if m.get("default"))

provider_cfg = config["generation"]["provider"]

default_provider = ai.Provider(
	type=provider_cfg["type"],
	api_key=provider_cfg["api_key"],
	model=DEFAULT_MODEL["id"],
	base_url=provider_cfg.get("base_url") or None
)

title_provider = ai.Provider(
	type=provider_cfg["type"],
	api_key=provider_cfg["api_key"],
	model=config["generation"]["title_model"],
	base_url=provider_cfg.get("base_url") or None
)

app = FastAPI(
	title=BRAND_NAME,
	docs_url=None,
	redoc_url=None,
	openapi_url=None
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def guess_mimetype(filename: str):
    mime, _ = mimetypes.guess_type(filename)
    return mime or "application/octet-stream"

templates.env.filters["guess_mimetype"] = guess_mimetype
templates.env.filters["from_json"] = json.loads

def ctx(request, **kwargs):
	user_id = db.get_user_id(request)
	return {
		"request": request,
		"BRAND_NAME": BRAND_NAME,
		"ICONS": ICONS,
		"MAX_UPLOAD_SIZE": MAX_UPLOAD_SIZE,
		"user_id": user_id,
		"models": models,
		**kwargs
	}

async def save_upload(chat_id: str, file: UploadFile) -> tuple[str, str]:
	original = file.filename or "unknown"
	resource = str(uuid4())
	extension = Path(file.filename or "").suffix
	path = UPLOAD_PATH / f"{chat_id}_{resource}{extension}"
	total_size = 0
	with path.open("wb") as buffer:
		while chunk := await file.read(1024 * 1024):
			total_size += len(chunk)
			if total_size > MAX_UPLOAD_SIZE:
				path.unlink(missing_ok=True)
				raise HTTPException(status_code=413, detail="File too large")
			buffer.write(chunk)

	id = f"{chat_id}_{resource}{extension}"
	db.set_file_meta(id, original, chat_id)

	return id, original

def stream_response(user_id: str, chat_id: str, request: Request, provider: ai.Provider, blocks_to_process: list | None = None, leaf_id: str | None = None, response_parent_id: str | None = None):
	if blocks_to_process is None:
		all_blocks = db.get_blocks(user_id, chat_id)
		if leaf_id:
			block_map = {block["id"]: block for block in all_blocks}
			branch_ids = set()
			current_id = leaf_id
			while current_id:
				branch_ids.add(current_id)
				current_block = block_map.get(current_id)
				if current_block and current_block["parent_id"]:
					current_id = current_block["parent_id"]
				else:
					break
			blocks_to_process = [block for block in all_blocks if block["id"] in branch_ids]
			blocks_to_process = sorted(blocks_to_process, key=lambda b: b["created_at"])
		else:
			if not all_blocks:
				blocks_to_process = []
			else:
				user_blocks = [b for b in all_blocks if b["role"] == "user"]
				if not user_blocks:
					blocks_to_process = []
				else:
					latest_user = max(user_blocks, key=lambda b: b["created_at"])
					block_map = {block["id"]: block for block in all_blocks}
					branch_ids = set()
					current_id = latest_user["id"]
					while current_id:
						branch_ids.add(current_id)
						current_block = block_map.get(current_id)
						if current_block and current_block["parent_id"]:
							current_id = current_block["parent_id"]
						else:
							break
					blocks_to_process = [block for block in all_blocks if block["id"] in branch_ids]
					blocks_to_process = sorted(blocks_to_process, key=lambda b: b["created_at"])

	if not blocks_to_process:
		raise HTTPException(status_code=400, detail="No blocks to process.")

	async def event_generator():
		full_content = ""
		content_block_id = None
		full_reasoning = ""
		reasoning_block_id = None
		first_block = True
		current_parent_id = response_parent_id

		try:
			async for event in ai.generate(blocks_to_process, provider):
				if await request.is_disconnected():
					break

				if isinstance(event, ai.TokenEvent):
					if full_reasoning:
						db.add_block(user_id, chat_id, "assistant", "reasoning", full_reasoning, block_id=reasoning_block_id, parent_id=current_parent_id if first_block else None)
						yield f"data: {json.dumps({"type": "BlockCreated", "id": reasoning_block_id, "block_type": "reasoning"})}\n\n"
						if first_block:
							current_parent_id = reasoning_block_id
							first_block = False
						full_reasoning = ""
						reasoning_block_id = None

					if not full_content:
						content_block_id = str(uuid4())

					full_content += event.content
					yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__, "block_id": content_block_id})}\n\n"

				elif isinstance(event, ai.ReasoningEvent):
					if full_content:
						db.add_block(user_id, chat_id, "assistant", "text", full_content, block_id=content_block_id, parent_id=current_parent_id if first_block else None)
						yield f"data: {json.dumps({"type": "BlockCreated", "id": content_block_id, "block_type": "text"})}\n\n"
						if first_block:
							current_parent_id = content_block_id
							first_block = False
						full_content = ""
						content_block_id = None

					if not full_reasoning:
						reasoning_block_id = str(uuid4())

					full_reasoning += event.content
					yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__, "block_id": reasoning_block_id})}\n\n"

				elif isinstance(event, ai.ToolStartEvent):
					if full_reasoning:
						db.add_block(user_id, chat_id, "assistant", "reasoning", full_reasoning, block_id=reasoning_block_id, parent_id=current_parent_id if first_block else None)
						yield f"data: {json.dumps({"type": "BlockCreated", "id": reasoning_block_id, "block_type": "reasoning"})}\n\n"
						if first_block:
							current_parent_id = reasoning_block_id
							first_block = False
						full_reasoning = ""
						reasoning_block_id = None
					if full_content:
						db.add_block(user_id, chat_id, "assistant", "text", full_content, block_id=content_block_id, parent_id=current_parent_id if first_block else None)
						yield f"data: {json.dumps({"type": "BlockCreated", "id": content_block_id, "block_type": "text"})}\n\n"
						if first_block:
							current_parent_id = content_block_id
							first_block = False
						full_content = ""
						content_block_id = None

					tool_call_id = str(uuid4())
					db.add_block(user_id, chat_id, "assistant", "tool_call", event.arguments, tool_name=event.name, tool_call_id=event.call_id, block_id=tool_call_id, parent_id=current_parent_id if first_block else None)
					yield f"data: {json.dumps({"type": "BlockCreated", "id": tool_call_id, "block_type": "tool_call"})}\n\n"
					yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__, "block_id": tool_call_id})}\n\n"
					if first_block:
						current_parent_id = tool_call_id
						first_block = False

				elif isinstance(event, ai.ToolResultEvent):
					tool_result_id = str(uuid4())
					db.add_block(user_id, chat_id, "tool", "tool_result", event.result, tool_name=event.name, tool_call_id=event.call_id, block_id=tool_result_id)
					yield f"data: {json.dumps({"type": "BlockCreated", "id": tool_result_id, "block_type": "tool_result"})}\n\n"
					yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__, "block_id": tool_result_id})}\n\n"

		finally:
			if full_reasoning:
				db.add_block(user_id, chat_id, "assistant", "reasoning", full_reasoning, block_id=reasoning_block_id, parent_id=current_parent_id if first_block else None)
				yield f"data: {json.dumps({"type": "BlockCreated", "id": reasoning_block_id, "block_type": "reasoning"})}\n\n"
				if first_block:
					current_parent_id = reasoning_block_id
					first_block = False
			if full_content:
				db.add_block(user_id, chat_id, "assistant", "text", full_content, block_id=content_block_id, parent_id=current_parent_id if first_block else None)
				yield f"data: {json.dumps({"type": "BlockCreated", "id": content_block_id, "block_type": "text"})}\n\n"

	return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/new")
@app.get("/")
async def root(request: Request, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return RedirectResponse(url="/login", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="new_chat.html",
		context=ctx(request, chats=db.get_chats(user_id))
	)

@app.get("/login")
async def login_page(request: Request, user_id: str = Depends(db.get_user_id)):
	if user_id:
		return RedirectResponse(url="/", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="auth.html",
		context=ctx(request, login=True)
	)

@app.post("/login")
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
	user = db.check_user(email, password)
	if user:
		response = RedirectResponse(url="/", status_code=302)
		response.set_cookie(key="access_token", value=jwt.encode(
			payload={"user_id": user},
			key=SECRET_KEY,
			algorithm="HS256"
		), httponly=True)
		return response
	return templates.TemplateResponse(
		request=request,
		name="auth.html",
		context=ctx(request, login=True, error=True)
	)

@app.get("/signup")
async def signup_page(request: Request, user_id: str = Depends(db.get_user_id)):
	if user_id:
		return RedirectResponse(url="/", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="auth.html",
		context=ctx(request, login=False)
	)

@app.post("/signup")
async def signup(request: Request, email: str = Form(...), password: str = Form(...)):
	user = db.create_user(email, password)
	if user:
		response = RedirectResponse(url="/", status_code=302)
		response.set_cookie(key="access_token", value=jwt.encode(
			payload={"user_id": user},
			key=SECRET_KEY,
			algorithm="HS256"
		), httponly=True)
		return response
	return templates.TemplateResponse(
		request=request,
		name="auth.html",
		context=ctx(request, login=False, error=True)
	)

@app.post("/api/chats")
async def new_chat(request: Request, background_tasks: BackgroundTasks, user_id: str = Depends(db.get_user_id), message: str = Form(...), files: list[UploadFile] = File(default=[])):
	if not user_id:
		return Response(status_code=401)

	chat = db.create_chat(user_id)
	if chat is None:
		return Response(status_code=401)

	async def name_chat():
		title = await ai.generate_title(message, title_provider)
		db.name_chat(chat, title or "Untitled")

	background_tasks.add_task(name_chat)

	for file in files:
		filename, original = await save_upload(chat, file)
		db.add_block(user_id, chat, "user", "file", json.dumps({"filename": filename, "original": original}))

	db.add_block(user_id, chat, "user", "text", message)
	return JSONResponse(content={"id": chat}, status_code=201)

@app.get("/api/chats/{chat_id}")
async def chat_info(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return Response(status_code=401)

	chat = db.get_chat(user_id, chat_id)
	if not chat:
		return Response(status_code=404)

	return {
		"title": chat["title"],
		"public": chat["public"],
		"created_at": chat["created_at"],
		"updated_at": chat["updated_at"]
	}

@app.patch("/api/chats/{chat_id}")
async def update_chat(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id), data: dict = Body(...)):
	if not user_id:
		return Response(status_code=401)

	db.update_chat(user_id, chat_id, **data)
	return Response(status_code=204)

@app.delete("/api/chats/{chat_id}")
async def delete_chat(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return Response(status_code=401)

	db.delete_chat(user_id, chat_id)
	for file in UPLOAD_PATH.glob(f"{chat_id}_*"):
		if file.is_file():
			file.unlink()

	return Response(status_code=204)

@app.post("/api/chats/{chat_id}/regenerate")
async def regenerate(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id), leaf_id: str = Body(None, embed=True), model: str = Body(DEFAULT_MODEL["id"], embed=True)):
	if not user_id:
		return Response(status_code=401)
	all_blocks = db.get_blocks(user_id, chat_id)
	block_map = {block["id"]: block for block in all_blocks}
	target_leaf_id = leaf_id
	if not target_leaf_id:
		user_blocks = [b for b in all_blocks if b["role"] == "user"]
		if not user_blocks:
			return stream_response(user_id, chat_id, request, ai.Provider(
				type=provider_cfg["type"],
				api_key=provider_cfg["api_key"],
				model=model,
				base_url=provider_cfg.get("base_url") or None
			), blocks_to_process=[])
		target_leaf_id = max(user_blocks, key=lambda b: b["created_at"])["id"]
	if target_leaf_id not in block_map:
		raise HTTPException(status_code=400, detail="leaf_id not found")
	if block_map[target_leaf_id]["role"] != "user":
		raise HTTPException(status_code=400, detail="leaf_id must be a user message id")
	branch_ids = set()
	current_id = target_leaf_id
	while current_id:
		branch_ids.add(current_id)
		current_block = block_map.get(current_id)
		if current_block and current_block["parent_id"]:
			current_id = current_block["parent_id"]
		else:
			break
	blocks_for_ai = [block for block in all_blocks if block["id"] in branch_ids]
	blocks_for_ai = sorted(blocks_for_ai, key=lambda b: b["created_at"])
	return stream_response(user_id, chat_id, request, ai.Provider(
		type=provider_cfg["type"],
		api_key=provider_cfg["api_key"],
		model=model,
		base_url=provider_cfg.get("base_url") or None
	), blocks_to_process=blocks_for_ai, response_parent_id=target_leaf_id)

@app.post("/api/chats/{chat_id}/send_message")
async def send_message(
    request: Request,
    chat_id: str,
    user_id: str = Depends(db.get_user_id),
    model: str = Form(DEFAULT_MODEL["id"]),
    message: str = Form(...),
    leaf_id: str = Form(None),
    files: list[UploadFile] = File(default=[]),
    file_ids: list[str] = Form([]),
):
	if not user_id:
		return Response(status_code=401)

	# Note for dummies: files are out of order. <- who is a dummy in this situation??
	# Too lazy to fix
	# Would require frontend changes too
	for file in files:
		filename, original = await save_upload(chat_id, file)
		db.add_block(user_id, chat_id, "user", "file", json.dumps({"filename": filename, "original": original}), parent_id=leaf_id)

	for file in file_ids:
		db.add_block(user_id, chat_id, "user", "file", json.dumps({"filename": filename, "original": db.get_file_original_name(filename)}), parent_id=leaf_id)

	user_block_id = db.add_block(user_id, chat_id, "user", "text", message, parent_id=leaf_id)

	async def event_generator_with_user_id():
		yield f"data: {json.dumps({"type": "UserMessageCreated", "id": user_block_id, "block_type": "text"})}\n\n"
		async for event in stream_response(
			user_id, chat_id, request, ai.Provider(
				type=provider_cfg["type"],
				api_key=provider_cfg["api_key"],
				model=model,
				base_url=provider_cfg.get("base_url") or None
			), leaf_id=user_block_id, response_parent_id=user_block_id
		).body_iterator:
			yield event

	return StreamingResponse(event_generator_with_user_id(), media_type="text/event-stream")

@app.get("/chat/{chat_id}")
async def get_chat(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return Response(status_code=401)
	blocks = db.get_blocks(user_id, chat_id)
	groups = []
	for block in blocks:
		role = "assistant" if block["role"] == "tool" else block["role"]
		if groups and groups[-1]["role"] == role and groups[-1]["last_id"] == block["parent_id"]:
			groups[-1]["blocks"].append(block)
			groups[-1]["last_id"] = block["id"]
		else:
			groups.append({"role": role, "first_id": block["id"], "last_id": block["id"], "blocks": [block]})
	return templates.TemplateResponse(
		request=request,
		name="chat.html",
		context=ctx(request, chats=db.get_chats(user_id), groups=groups, chat_id=chat_id)
	)

@app.get("/chat/{chat_id}/uploads/{upload_id}")
async def get_upload(request: Request, chat_id: str, upload_id: str):
	path = (UPLOAD_PATH / f"{upload_id}").resolve()
	if not path.is_relative_to(UPLOAD_PATH.resolve()):
		raise HTTPException(status_code=403, detail="fuck you")
	if not upload_id.startswith(f"{chat_id}_"):
	    raise HTTPException(status_code=403, detail="wrong chat")
	if path.exists():
		return FileResponse(path)
	raise HTTPException(status_code=404, detail="Upload not found")

@app.get("/recents")
@app.get("/chats")
async def chats(request: Request, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return RedirectResponse(url="/login", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="recents.html",
		context=ctx(request, chats=db.get_chats(user_id))
	)
