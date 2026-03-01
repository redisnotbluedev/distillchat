import sqlite3, os, jwt
from uuid import uuid4
from pwdlib import PasswordHash
from fastapi import Request
from dotenv import load_dotenv
from contextlib import contextmanager

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "changeme123")

@contextmanager
def _get_db():
	conn = sqlite3.connect("data.db")
	conn.row_factory = sqlite3.Row
	try:
		yield conn
		conn.commit()
	except Exception:
		conn.rollback()
		raise
	finally:
		conn.close()

# Makes it easy to change the algorithm
def _get_hasher():
	return PasswordHash.recommended()

def _init():
	with _get_db() as conn:
		conn.executescript("""
			CREATE TABLE users (
				id TEXT PRIMARY KEY,
				email TEXT UNIQUE NOT NULL,
				password_hash TEXT NOT NULL,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE conversations (
				id TEXT PRIMARY KEY,
				user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				title TEXT NOT NULL DEFAULT "New Conversation",
				active_leaf_id TEXT REFERENCES messages(id),
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE messages (
				id TEXT PRIMARY KEY,
				conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
				parent_id TEXT REFERENCES messages(id),
				role TEXT NOT NULL,
				type TEXT NOT NULL DEFAULT "text",
				content TEXT,
				tool_name TEXT,
				tool_call_id TEXT,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			PRAGMA journal_mode=WAL;
			PRAGMA foreign_keys=ON;
		""")

def get_user_id(request: Request):
	token = request.cookies.get("access_token")
	if not token:
		return None

	try:
		payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
		return payload.get("user_id")
	except jwt.PyJWTError:
		return None

def check_user(email: str, password: str):
	with _get_db() as conn:
		user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()

	if user is None:
		return None

	hasher = _get_hasher()
	if not hasher.verify(password, user["password_hash"]):
		return None

	return user["id"]

def create_user(email: str, password: str):
	hasher = _get_hasher()
	id = str(uuid4())

	with _get_db() as conn:
		user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
		if user is not None:
			return None

		conn.execute("INSERT INTO users (id, email, password_hash) VALUES (?, ?, ?)", (id, email, hasher.hash(password)))
		return id

_init()
