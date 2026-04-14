# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>

import json, logging, mimetypes, re, sys, jwt, pyaml_env, ai, db, zipfile, tempfile, os, io, hashlib, asyncio
import ijson.backends.python as ijson
from typing import Literal, Type
from pathlib import Path
from uuid import uuid4, UUID
from dotenv import load_dotenv
from fastapi import BackgroundTasks, Body, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict

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
AI_NAME = config["brand"]["ai_name"]
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

def optional_model(cls: Type[BaseModel]):
    for field in cls.model_fields.values():
        field.default = ""
    cls.model_rebuild(force=True)
    return cls

def hashed_uuid(text):
	return UUID(bytes=hashlib.sha256(text.encode()).digest()[:16], version=4).hex

@optional_model
class SettingsPatch(BaseModel):
	model_config = ConfigDict(extra="forbid")

	name: str
	system_prompt: str
	theme: str
	variation: str
	font: str

class ByteLimitedStream(io.RawIOBase):
	def __init__(self, stream, limit):
		self.stream = stream
		self.limit = limit
		self.bytes_read = 0

	def read(self, n=-1):
		chunk = self.stream.read(n)
		self.bytes_read += len(chunk)
		if self.bytes_read > self.limit:
			raise OverflowError("Individual file too large.")
		return chunk

	def readable(self): return True

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
		"AI_NAME": AI_NAME,
		"ICONS": ICONS,
		"MAX_UPLOAD_SIZE": MAX_UPLOAD_SIZE,
		"user_id": user_id,
		"models": models,
		**kwargs
	}

def chat_ctx(request, **kwargs):
	user_id = db.get_user_id(request)
	chats = db.get_chats(user_id)
	data = db.get_user_info(user_id)
	total_chats = chats[0]["total_count"] if chats else 0
	return ctx(request, user=data, chats=chats, total_chats=total_chats, **kwargs)

@app.get("/api/chats")
async def list_chats(user_id: str = Depends(db.get_user_id), limit: int = 20, offset: int = 0, query: str | None = None):
	if not user_id:
		return Response(status_code=401)
	chats = db.get_chats(user_id, limit, offset, query)
	total_chats = chats[0]["total_count"] if chats else 0
	return {
		"chats": [
			{
				"id": chat["id"],
				"title": chat["title"],
				"updated_at": chat["updated_at"].isoformat(),
				"created_at": chat["created_at"].isoformat()
			} for chat in chats
		],
		"total_count": total_chats
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

def stream_response(user_id: str, chat_id: str, request: Request, provider: ai.Provider, messages_to_process: list | None = None, leaf_id: str | None = None, response_parent_id: str | None = None):
	if messages_to_process is None:
		all_messages = db.get_messages(user_id, chat_id)
		target_id = leaf_id or response_parent_id

		if target_id:
			msg_map = {msg["id"]: msg for msg in all_messages}
			branch_ids = set()
			current_id = target_id
			while current_id:
				branch_ids.add(current_id)
				current_msg = msg_map.get(current_id)
				if current_msg and current_msg["parent_id"]:
					current_id = current_msg["parent_id"]
				else:
					break
			messages_to_process = [msg for msg in all_messages if msg["id"] in branch_ids]
			messages_to_process = sorted(messages_to_process, key=lambda m: m["created_at"])
			if response_parent_id is None:
				response_parent_id = target_id
		else:
			messages_to_process = []

	if not messages_to_process:
		raise HTTPException(status_code=400, detail="No messages to process.")

	async def event_generator():
		full_content = ""
		content_block_id = None
		full_reasoning = ""
		reasoning_block_id = None
		current_parent_id = response_parent_id
		response_message_id = db.add_message(user_id, chat_id, "assistant", parent_id=current_parent_id)
		yield f"data: {json.dumps({"type": "MessageCreated", "id": response_message_id, "role": "assistant"})}\n\n"

		order_index = 0
		try:
			async for event in ai.generate(messages_to_process, provider):
				if await request.is_disconnected():
					break

				if isinstance(event, ai.TokenEvent):
					if full_reasoning:
						db.add_content_block(response_message_id, "reasoning", full_reasoning, order_index=order_index, block_id=reasoning_block_id)
						order_index += 1
						full_reasoning = ""
						reasoning_block_id = None

					if not full_content:
						content_block_id = str(uuid4())
						yield f"data: {json.dumps({"type": "ContentBlockCreated", "id": content_block_id, "block_type": "text"})}\n\n"

					full_content += event.content
					yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__})}\n\n"

				elif isinstance(event, ai.ReasoningEvent):
					if full_content.strip():
						db.add_content_block(response_message_id, "text", full_content, order_index=order_index, block_id=content_block_id)
						order_index += 1
						full_content = ""
						content_block_id = None

					if not full_reasoning:
						reasoning_block_id = str(uuid4())
						yield f"data: {json.dumps({"type": "ContentBlockCreated", "id": reasoning_block_id, "block_type": "reasoning"})}\n\n"

					full_reasoning += event.content
					yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__})}\n\n"

				elif isinstance(event, ai.ToolStartEvent):
					if full_reasoning:
						db.add_content_block(response_message_id, "reasoning", full_reasoning, order_index=order_index, block_id=reasoning_block_id)
						order_index += 1
						full_reasoning = ""
						reasoning_block_id = None
					if full_content.strip():
						db.add_content_block(response_message_id, "text", full_content, order_index=order_index, block_id=content_block_id)
						order_index += 1
						full_content = ""
						content_block_id = None

					block_id = str(uuid4())
					db.add_content_block(response_message_id, "tool_call", event.arguments, tool_name=event.name, tool_call_id=event.call_id, order_index=order_index, block_id=block_id)
					order_index += 1
					yield f"data: {json.dumps({"type": "ContentBlockCreated", "id": block_id, "block_type": "tool_call"})}\n\n"
					yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__})}\n\n"

				elif isinstance(event, ai.ToolResultEvent):
					db.add_content_block(response_message_id, "tool_result", event.result, tool_name=event.name, tool_call_id=event.call_id, order_index=order_index)
					order_index += 1
					yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__})}\n\n"

		finally:
			if full_reasoning:
				db.add_content_block(response_message_id, "reasoning", full_reasoning, order_index=order_index, block_id=reasoning_block_id)
			if full_content.strip():
				db.add_content_block(response_message_id, "text", full_content, order_index=order_index, block_id=content_block_id)

	return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/new")
@app.get("/")
async def root(request: Request, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return RedirectResponse(url="/login", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="new_chat.html",
		context=chat_ctx(request)
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

@app.get("/register")
@app.get("/signup")
async def signup_page(request: Request, user_id: str = Depends(db.get_user_id)):
	if user_id:
		return RedirectResponse(url="/", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="auth.html",
		context=ctx(request, login=False)
	)

@app.post("/register")
@app.post("/signup")
async def signup(request: Request, email: str = Form(...), name: str = Form(...), password: str = Form(...)):
	user = db.create_user(email, password, name)
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

@app.get("/logout")
async def logout(request: Request, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return RedirectResponse(url="/login", status_code=302)

	response = RedirectResponse(url="/", status_code=302)
	response.delete_cookie(key="access_token", httponly=True)
	return response

@app.post("/api/chats")
async def new_chat(request: Request, background_tasks: BackgroundTasks, user_id: str = Depends(db.get_user_id), message: str = Form(...), files: list[UploadFile] = File(default=[])):
	if not user_id:
		return Response(status_code=401)

	chat = db.create_chat(user_id)
	if chat is None:
		return Response(status_code=401)

	async def name_chat():
		all_messages = db.get_messages(user_id, chat)
		title = await ai.generate_title(all_messages, title_provider)
		db.name_chat(chat, title or "Untitled")

	background_tasks.add_task(name_chat)

	message_id = db.add_message(user_id, chat, "user")
	for file in files:
		file_id, original = await save_upload(chat, file)
		db.add_attachment(message_id, file_id)

	db.add_content_block(message_id, "text", message)
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
	all_messages = db.get_messages(user_id, chat_id)
	msg_map = {msg["id"]: msg for msg in all_messages}
	target_leaf_id = leaf_id
	if not target_leaf_id:
		user_messages = [m for m in all_messages if m["role"] == "user"]
		if not user_messages:
			return stream_response(user_id, chat_id, request, ai.Provider(
				type=provider_cfg["type"],
				api_key=provider_cfg["api_key"],
				model=model,
				base_url=provider_cfg.get("base_url") or None
			), messages_to_process=[])
		user_ids = {m["id"] for m in user_messages}
		parent_ids = {m["parent_id"] for m in user_messages if m["parent_id"] in user_ids}
		leaves = [m for m in user_messages if m["id"] not in parent_ids]
		target_leaf_id = leaves[-1]["id"] if leaves else user_messages[-1]["id"]
	if target_leaf_id not in msg_map:
		raise HTTPException(status_code=400, detail="leaf_id not found")
	if msg_map[target_leaf_id]["role"] != "user":
		raise HTTPException(status_code=400, detail="leaf_id must be a user message id")
	branch_ids = set()
	current_id = target_leaf_id
	while current_id:
		branch_ids.add(current_id)
		current_msg = msg_map.get(current_id)
		if current_msg and current_msg["parent_id"]:
			current_id = current_msg["parent_id"]
		else:
			break
	messages_for_ai = [msg for msg in all_messages if msg["id"] in branch_ids]
	messages_for_ai = sorted(messages_for_ai, key=lambda m: m["created_at"])
	return stream_response(user_id, chat_id, request, ai.Provider(
		type=provider_cfg["type"],
		api_key=provider_cfg["api_key"],
		model=model,
		base_url=provider_cfg.get("base_url") or None
	), messages_to_process=messages_for_ai, leaf_id=target_leaf_id, response_parent_id=target_leaf_id)

@app.post("/api/chats/{chat_id}/send-message")
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

	message_id = db.add_message(user_id, chat_id, "user", parent_id=leaf_id)
	for file in files:
		file_id, original = await save_upload(chat_id, file)
		db.add_attachment(message_id, file_id)

	for file_id in file_ids:
		db.add_attachment(message_id, file_id)

	db.add_content_block(message_id, "text", message)

	async def event_generator_with_user_id():
		yield f"data: {json.dumps({"type": "UserMessageCreated", "id": message_id})}\n\n"
		async for event in stream_response(
			user_id, chat_id, request, ai.Provider(
				type=provider_cfg["type"],
				api_key=provider_cfg["api_key"],
				model=model,
				base_url=provider_cfg.get("base_url") or None
			), leaf_id=message_id, response_parent_id=message_id
		).body_iterator:
			yield event

	return StreamingResponse(event_generator_with_user_id(), media_type="text/event-stream")

@app.get("/chat/{chat_id}")
async def get_chat(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return Response(status_code=401)
	messages = db.get_messages(user_id, chat_id)
	return templates.TemplateResponse(
		request=request,
		name="chat.html",
		context=chat_ctx(request, messages=messages, chat_id=chat_id)
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
		context=chat_ctx(request)
	)

@app.get("/settings")
@app.get("/settings/{page}")
async def settings(request: Request, page: Literal["general", "appearance", "account", "data-controls"] = "general", user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return RedirectResponse(url="/login", status_code=302)

	return templates.TemplateResponse(
		request=request,
		name="settings.html",
		context=chat_ctx(request, page=page)
	)

@app.patch("/api/settings")
async def patch_settings(request: SettingsPatch, user_id: str = Depends(db.get_user_id)):
	settings = db.get_user_info(user_id)
	del settings["email"]
	db.update_settings(user_id, **(settings | request.model_dump(exclude_none=True, exclude_defaults=True)))

@app.get("/api/export")
async def export_data(tasks: BackgroundTasks, user_id: str = Depends(db.get_user_id)):
	chats = db.get_chats(user_id)
	data = []
	uploads = set()
	for chat in chats:
		messages_data = []
		for msg in db.get_messages(user_id, chat["id"]):
			m = {
				"id": msg["id"],
				"parent": msg["parent_id"],
				"role": msg["role"],
				"created_at": msg["created_at"].isoformat(),
				"blocks": msg["blocks"],
				"attachments": msg["attachments"]
			}
			messages_data.append(m)
			for a in msg["attachments"]:
				uploads.add(a["file_id"])

		data.append({
			"id": chat["id"],
			"title": chat["title"],
			"public": chat["public"],
			"created_at": chat["created_at"].isoformat(),
			"updated_at": chat["updated_at"].isoformat(),
			"messages": messages_data
		})

	tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
	tmp.close()
	with zipfile.ZipFile(tmp.name, "w") as zf:
		zf.writestr("conversations.json", json.dumps(data))
		user = db.get_user_info(user_id) | {"user_id": user_id}
		zf.writestr("user.json", json.dumps(user))
		for upload in uploads:
			zf.write(UPLOAD_PATH / upload, f"attachments/{upload}")

	tasks.add_task(os.unlink, tmp.name)
	return FileResponse(tmp.name, filename="export.zip")

@app.get("/import-data")
async def import_data_page(request: Request, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return RedirectResponse(url="/login", status_code=302)

	return templates.TemplateResponse(
		request=request,
		name="import.html",
		context=chat_ctx(request)
	)

@app.post("/api/import")
async def import_data(user_id: str = Depends(db.get_user_id), format: str = Form(...), include: list[str] = Form(default=[]), file: UploadFile = File(...)):
	async def generate():
		def do_import(queue: asyncio.Queue):
			try:
				bytes = 0
				completed_chats = 0

				with zipfile.ZipFile(file.file) as zf:
					total_uncompressed_size = sum(z.file_size for z in zf.infolist())
					if total_uncompressed_size > 100 * 1024 * 1024: # 100MB limit
						raise HTTPException(413)

					settings = db.get_user_info(user_id)
					match format:
						case "anthropic":
							if "name" in include:
								with zf.open("users.json") as f:
									content = f.read(2 * 1024 * 1024 + 1) # 2MB limit
									if len(content) > 2 * 1024 * 1024:
										raise HTTPException(413)
									settings |= {"name": json.loads(content)[0]["full_name"]}
							if "memory" in include:
								with zf.open("memories.json") as f:
									content = f.read(2 * 1024 * 1024 + 1) # 2MB limit
									if len(content) > 2 * 1024 * 1024:
										raise HTTPException(413)
									settings |= {"memory": json.loads(content)[0]["conversations_memory"]}

							if "chats" in include:
								with zf.open("conversations.json") as f:
									stream = ByteLimitedStream(f, limit=100 * 1024 * 1024)
									chats = ijson.items(stream, "item", use_float=True)

									for chat in chats:
										try:
											with db.transaction() as conn:
												chat_id = db.import_chat(user_id, chat["name"] or "Untitled", chat["created_at"], chat["updated_at"], conn=conn)
												message_uuid_map = {}
												blocks = 0

												for message in chat["chat_messages"]:
													if message is None:
														continue

													if not "parent_message_uuid" in message:
														continue

													parent = message["parent_message_uuid"]
													if parent == "00000000-0000-4000-8000-000000000000":
														parent = None

													parent = message_uuid_map.setdefault(parent, str(uuid4()))

													id = message["uuid"]
													id = message_uuid_map.setdefault(id, str(uuid4()))

													db.import_message(chat_id, id, parent, {"human": "user"}.get(message["sender"], message["sender"]), message["updated_at"], conn=conn)

													last_tool_id = None
													last_time = message["updated_at"]
													for i in range(len(message["content"])):
														block = message["content"][i]
														if block["start_timestamp"]:
															last_time = block["start_timestamp"]
														match block["type"]:
															case "text":
																if not block["text"].strip():
																	continue
																db.import_block(id, "text", block["text"], None, None, i, last_time, conn=conn)
																blocks += 1
															case "thinking":
																if not block["thinking"].strip():
																	continue
																db.import_block(id, "reasoning", block["thinking"], None, None, i, last_time, conn=conn)
																blocks += 1
															case "tool_use":
																if not block["input"]:
																	continue

																if block["id"]:
																	# The tool IDs in Claude data exports use a custom format ie "toolu_01QpVQ66AyZG6hb1sykGmyt7", this normalizes to a UUID
																	last_tool_id = hashed_uuid(block["id"])
																else:
																	last_tool_id = str(uuid4())
																db.import_block(id, "tool_call", json.dumps(block["input"]), block["name"], last_tool_id, i, last_time, conn=conn)
																blocks += 1
															case "tool_result":
																if not block["content"]:
																	continue

																if block["tool_use_id"]:
																	last_tool_id = hashed_uuid(block["tool_use_id"])
																db.import_block(id, "tool_result", json.dumps(block["content"]), block["name"], last_tool_id, i, last_time, conn=conn)
																blocks += 1
												if blocks == 0:
													raise db.SkipChat()

												completed_chats += 1
												bytes = stream.bytes_read
												queue.put_nowait({"read": stream.bytes_read, "chats": completed_chats})
										except db.SkipChat: ...
						case _:
							raise HTTPException(501)
					db.update_settings(user_id, **settings)
			finally:
				file.file.close()
				queue.put_nowait({"done": True, "read": bytes, "chats": completed_chats})

		queue = asyncio.Queue()
		loop = asyncio.get_event_loop()
		task = loop.run_in_executor(None, do_import, queue)

		while True:
			message = await queue.get()
			yield f"data: {json.dumps(message)}\n\n"
			if message.get("done"):
				break

		await task

	return StreamingResponse(generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})

@app.delete("/api/delete-account")
async def delete_account(user_id: str = Depends(db.get_user_id), email: str = Body(..., embed=True), password: str = Body(..., embed=True)):
	if db.check_user(email, password, user_id):
		response = RedirectResponse(url="/", status_code=302)
		response.delete_cookie(key="access_token", httponly=True)

		chats = db.get_chats(user_id)

		# Remove uploads BEFORE the deletion so we still have the chat list
		for chat in chats:
			for file in UPLOAD_PATH.glob(f"{chat["id"]}_*"):
				if file.is_file():
					file.unlink()

		db.delete_account(user_id)

		return response
