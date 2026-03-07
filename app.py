# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>

import os, db, jwt, ai, json
from dotenv import load_dotenv
from pathlib import Path
from fastapi import FastAPI, Request, Depends, Form, Body
from fastapi.responses import RedirectResponse, Response, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()
BRAND_NAME = os.getenv("BRAND_NAME", "My App")
SECRET_KEY = os.getenv("SECRET_KEY", "changeme123")
ICONS = [f.stem for f in Path("templates/icons").glob("*.svg")]

app = FastAPI(
	title=BRAND_NAME,
	docs_url=None,
	redoc_url=None,
	openapi_url=None
)

client = ai.Client()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

def ctx(request, **kwargs):
	user_id = db.get_user_id(request)
	return {
		"request": request,
		"BRAND_NAME": BRAND_NAME,
		"ICONS": ICONS,
		"user_id": user_id,
		**kwargs
	}

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
	else:
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
	else:
		return templates.TemplateResponse(
			request=request,
			name="auth.html",
			context=ctx(request, login=False, error=True)
		)

@app.post("/api/chats")
async def new_chat(request: Request, user_id: str = Depends(db.get_user_id), message: str = Body(embed=True)):
	if not user_id:
		return Response(status_code=401)

	chat = db.create_chat(user_id, message)
	if chat is None:
		return Response(status_code=401)

	return JSONResponse(content={"id": chat}, status_code=201)

@app.post("/api/chats/{chat_id}/regenerate")
async def regenerate(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return Response(status_code=401)

	messages = db.get_messages(user_id, chat_id)
	async def event_generator():
		full_content = ""
		async for event in client.generate("gpt-4o", messages):
			if isinstance(event, ai.TokenEvent):
				full_content += event.content
			elif isinstance(event, ai.ToolStartEvent):
				if full_content:
					db.add_message(user_id, chat_id, full_content, "assistant")
					full_content = ""
				db.add_message(user_id, chat_id, event.arguments, "assistant", type="tool_call", tool_name=event.name, tool_call_id=event.call_id)
			elif isinstance(event, ai.ToolResultEvent):
				db.add_message(user_id, chat_id, event.result, "tool", type="tool_result", tool_name=event.name, tool_call_id=event.call_id)

			yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__})}\n\n"

		if full_content:
			db.add_message(user_id, chat_id, full_content, "assistant")

	return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.post("/api/chats/{chat_id}/send_message")
async def send_message(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id), message: str = Body(embed=True)):
	if not user_id:
		return Response(status_code=401)

	db.add_message(user_id, chat_id, message, "user")
	messages = db.get_messages(user_id, chat_id)

	async def event_generator():
		full_content = ""
		async for event in client.generate("gpt-4o", messages):
			if isinstance(event, ai.TokenEvent):
				full_content += event.content
			elif isinstance(event, ai.ToolStartEvent):
				if full_content:
					db.add_message(user_id, chat_id, full_content, "assistant")
					full_content = ""
				db.add_message(user_id, chat_id, event.arguments, "assistant", type="tool_call", tool_name=event.name, tool_call_id=event.call_id)
			elif isinstance(event, ai.ToolResultEvent):
				db.add_message(user_id, chat_id, event.result, "tool", type="tool_result", tool_name=event.name, tool_call_id=event.call_id)

			yield f"data: {json.dumps(event.__dict__ | {"type": type(event).__name__})}\n\n"

		if full_content:
			db.add_message(user_id, chat_id, full_content, "assistant")

	return StreamingResponse(event_generator(), media_type="text/event-stream")

@app.get("/chat/{chat_id}")
async def get_chat(request: Request, chat_id: str, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return Response(status_code=401)

	messages = db.get_messages(user_id, chat_id)
	return templates.TemplateResponse(
		request=request,
		name="chat.html",
		context=ctx(request, chats=db.get_chats(user_id), messages=messages, chat_id=chat_id)
	)
