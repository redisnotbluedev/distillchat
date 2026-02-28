from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

app = FastAPI(
	title="app", # Change this when you think of a name!!!
	docs_url=None,
	redoc_url=None,
	openapi_url=None
)

app.mount("/", StaticFiles(directory="static", html=True), name="static")
