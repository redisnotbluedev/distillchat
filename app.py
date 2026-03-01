import os
from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

load_dotenv()
BRAND_NAME = os.getenv("BRAND_NAME", "My App")

app = FastAPI(
	title=BRAND_NAME,
	docs_url=None,
	redoc_url=None,
	openapi_url=None
)

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/")
async def root(request: Request):
	return templates.TemplateResponse(
		request=request,
		name="new_chat.html",
		context={"BRAND_NAME": BRAND_NAME}
	)
