import os, db, jwt
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()
BRAND_NAME = os.getenv("BRAND_NAME", "My App")
SECRET_KEY = os.getenv("SECRET_KEY", "changeme123")

app = FastAPI(
	title=BRAND_NAME,
	docs_url=None,
	redoc_url=None,
	openapi_url=None
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def root(request: Request, user_id: str = Depends(db.get_user_id)):
	if not user_id:
		return RedirectResponse(url="/login", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="new_chat.html",
		context={"BRAND_NAME": BRAND_NAME, "user_id": user_id, "chats": db.get_chats(user_id)}
	)

@app.get("/login")
async def login_page(request: Request, user_id: str = Depends(db.get_user_id)):
	if user_id:
		return RedirectResponse(url="/", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="auth.html",
		context={"BRAND_NAME": BRAND_NAME, "login": True}
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
			context={"BRAND_NAME": BRAND_NAME, "login": True, "error": True}
		)

@app.get("/signup")
async def signup_page(request: Request, user_id: str = Depends(db.get_user_id)):
	if user_id:
		return RedirectResponse(url="/", status_code=302)
	return templates.TemplateResponse(
		request=request,
		name="auth.html",
		context={"BRAND_NAME": BRAND_NAME, "login": False}
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
			context={"BRAND_NAME": BRAND_NAME, "login": False, "error": True}
		)
