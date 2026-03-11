# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>

import os, db, jwt, ai, json, re, mimetypes
from dotenv import load_dotenv
from pathlib import Path
from uuid import uuid4
from fastapi import FastAPI, Request, Depends, Form, File, UploadFile, HTTPException, BackgroundTasks, Body
from fastapi.responses import RedirectResponse, Response, JSONResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

def parse_size(size):
	units = {"B": 1, "K": 1024, "M": 1024**2, "G": 1024**3, "T": 1024**4}
	match = re.match(r"(\d+\.?\d*)\s*([a-zA-Z]?)", str(size).strip())
	if not match:
		return 0
	number, unit = match.groups()
	return int(float(number) * units.get(unit.upper(), 1))

load_dotenv()
BRAND_NAME = os.getenv("BRAND_NAME", "My App")
SECRET_KEY = os.getenv("SECRET_KEY", "changeme123")
ICONS = [f.stem for f in Path("templates/icons").glob("*.svg")]

MAX_UPLOAD_SIZE = parse_size(os.getenv("MAX_UPLOAD_SIZE", "30M"))
UPLOAD_PATH = Path("./uploads")
UPLOAD_PATH.mkdir(exist_ok=True)

default_provider = ai.Provider(
	type="openai",
	api_key=os.getenv("OPENAI_API_KEY", ""),
	model="qwen/qwen3-vl-235b-a22b-thinking",
	base_url=os.getenv("OPENAI_BASE_URL") or None
)

title_provider = ai.Provider(
	type="openai",
	api_key=os.getenv("OPENAI_API_KEY", ""),
	model="nvidia/nemotron-3-nano-30b-a3b:free",
	base_url=os.getenv("OPENAI_BASE_URL") or None
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
	return f"{chat_id}_{resource}{extension}", original

def stream_response(user_id: str, chat_id: str):
	blocks = db.get_blocks(user_id, chat_id)

	async def event_generator():
		full_content = ""
		full_reasoning = ""
		async for event in ai.generate(blocks, default_provider):
			if isinstance(event, ai.TokenEvent):
				if full_reasoning:
					db.add_block(user_id, chat_id, "assistant", "reasoning", full_reasoning)
					full_reasoning = ""
				full_content += event.content
			elif isinstance(event, ai.ReasoningEvent):
				if full_content:
					db.add_block(user_id, chat_id, "assistant", "text", full_content)
					full_content = ""
				full_reasoning += event.content
			elif isinstance(event, ai.ToolStartEvent):
				if full_reasoning:
					db.add_block(user_id, chat_id, "assistant", "reasoning", full_reasoning)
					full_reasoning = ""
				if full_content:
					db.add_block(user_id, chat_id, "assistant", "text", full_content)
					full_content = ""
				db.add_block(user_id, chat_id, "assistant", "tool_call", event.arguments, tool_name=event.name, tool_call_id=event.call_id)
			elif isinstance(event, ai.ToolResultEvent):
				db.add_block(user_id, chat_id, "tool", "tool_result", event.result, tool_name=event.name, tool_call_id=event.call_id)

			yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__})}\n\n"

		if full_reasoning:
			db.add_block(user_id, chat_id, "assistant", "reasoning", full_reasoning)
		if full_content:
			db.add_block(user_id, chat_id, "assistant", "text", full_content)

	return StreamingResponse(event_generator(), media_type="text/event-stream")

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

@app.post("/api/chats/{chat_id}/regenerate")
async def regenerate(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return Response(status_code=401)
	return stream_response(user_id, chat_id)

@app.post("/api/chats/{chat_id}/send_message")
async def send_message(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id), message: str = Form(...), files: list[UploadFile] = File(default=[])):
	if not user_id:
		return Response(status_code=401)

	for file in files:
		filename, original = await save_upload(chat_id, file)
		db.add_block(user_id, chat_id, "user", "file", json.dumps({"filename": filename, "original": original}))

	db.add_block(user_id, chat_id, "user", "text", message)
	return stream_response(user_id, chat_id)

@app.get("/chat/{chat_id}")
async def get_chat(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return Response(status_code=401)
	blocks = db.get_blocks(user_id, chat_id)
	return templates.TemplateResponse(
		request=request,
		name="chat.html",
		context=ctx(request, chats=db.get_chats(user_id), messages=blocks, chat_id=chat_id)
	)

@app.get("/chat/{chat_id}/uploads/{upload_id}")
async def get_upload(request: Request, chat_id: str, upload_id: str):
	path = UPLOAD_PATH / f"{upload_id}"
	if path.exists():
		return FileResponse(path)
	raise HTTPException(status_code=404, detail="Upload not found")
