# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
import sqlite3, os, jwt, datetime, json
from typing import Iterator
from uuid import uuid4
from pwdlib import PasswordHash
from fastapi import HTTPException, Request
from dotenv import load_dotenv
from contextlib import contextmanager

load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY", "changeme123")

@contextmanager
def _get_db() -> Iterator[sqlite3.Cursor]:
	sqlite3.register_converter("TIMESTAMP", lambda b: datetime.datetime.fromisoformat(b.decode()).replace(tzinfo=datetime.timezone.utc))
	conn = sqlite3.connect("data.db", detect_types=sqlite3.PARSE_DECLTYPES)
	conn.row_factory = sqlite3.Row
	try:
		yield conn
		conn.commit()
	except Exception:
		conn.rollback()
		raise
	finally:
		conn.close()

def _get_hasher():
	return PasswordHash.recommended()

def _init():
	with _get_db() as conn:
		conn.executescript("""
			CREATE TABLE IF NOT EXISTS users (
				id TEXT PRIMARY KEY,
				email TEXT UNIQUE NOT NULL,
				password_hash TEXT NOT NULL,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				name TEXT NOT NULL DEFAULT "Guest",
				settings TEXT NOT NULL DEFAULT "{}"
			);

			CREATE TABLE IF NOT EXISTS conversations (
				id TEXT PRIMARY KEY,
				user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				title TEXT NOT NULL DEFAULT "Untitled",
				public INTEGER NOT NULL DEFAULT 0,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS blocks (
				id TEXT PRIMARY KEY,
				conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
				parent_id TEXT REFERENCES blocks(id),
				role TEXT NOT NULL,
				type TEXT NOT NULL DEFAULT "text",
				content TEXT,
				tool_name TEXT,
				tool_call_id TEXT,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS uploads (
				filename TEXT PRIMARY KEY,
				orignal TEXT NOT NULL,
				chat_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE
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

def create_user(email: str, password: str, name: str):
	hasher = _get_hasher()
	id = str(uuid4())

	with _get_db() as conn:
		user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
		if user is not None:
			return None

		conn.execute("INSERT INTO users (id, email, password_hash, name) VALUES (?, ?, ?, ?)", (id, email, hasher.hash(password), name))
		return id

def get_chats(user_id: str):
	with _get_db() as conn:
		return conn.execute("SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()

def create_chat(user_id: str, title: str = "Untitled"):
	try:
		with _get_db() as conn:
			id = str(uuid4())
			conn.execute("INSERT INTO conversations (id, user_id, title) VALUES (?, ?, ?)", (id, user_id, title))
			return id
	except sqlite3.IntegrityError as e:
		if getattr(e, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_FOREIGNKEY":
			return None
		else:
			raise

def get_blocks(user_id: str, chat_id: str):
	with _get_db() as conn:
		chat = conn.execute("SELECT * FROM conversations WHERE id = ?", (chat_id,)).fetchone()
		if chat is None:
			raise HTTPException(status_code=404)
		if chat["user_id"] != user_id:
			raise HTTPException(status_code=403)

		return conn.execute("SELECT * FROM blocks WHERE conversation_id = ? ORDER BY created_at ASC", (chat_id,)).fetchall()

def add_block(user_id: str, chat_id: str, role: str, type: str = "text", content: str | None = None, tool_name: str | None = None, tool_call_id: str | None = None, parent_id: str | None = None, block_id: str | None = None):
	with _get_db() as conn:
		chat = conn.execute("SELECT * FROM conversations WHERE id = ?", (chat_id,)).fetchone()
		if chat is None:
			raise HTTPException(status_code=404)
		if chat["user_id"] != user_id:
			raise HTTPException(status_code=403)

		# If parent_id is not explicitly provided, find the latest block in the conversation.
		if parent_id is None:
			last_block = conn.execute(
				"SELECT id FROM blocks WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
				(chat_id,)
			).fetchone()
			parent_id = last_block["id"] if last_block else None

		id = block_id or str(uuid4())
		conn.execute(
			"INSERT INTO blocks (id, conversation_id, parent_id, role, type, content, tool_name, tool_call_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
			(id, chat_id, parent_id, role, type, content, tool_name, tool_call_id)
		)
		conn.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
		return id

def name_chat(chat_id: str, title: str):
	with _get_db() as conn:
		conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, chat_id))

def get_chat(user_id: str, chat_id: str):
	with _get_db() as conn:
		chat = conn.execute("SELECT * FROM conversations WHERE id = ? AND user_id = ?", (chat_id, user_id)).fetchone()
		return chat

def update_chat(user_id: str, chat_id: str, title: str | None = None, public: bool | None = None):
	with _get_db() as conn:
		if public is None and title is not None:
			conn.execute("UPDATE conversations SET title = ? WHERE id = ? AND user_id = ?", (title, chat_id, user_id))
		elif public is not None and title is None:
			conn.execute("UPDATE conversations SET public = ? WHERE id = ? AND user_id = ?", (public, chat_id, user_id))
		else:
			conn.execute("UPDATE conversations SET title = ?, public = ? WHERE id = ? AND user_id = ?", (title, public, chat_id, user_id))

def delete_chat(user_id: str, chat_id: str):
	with _get_db() as conn:
		rows = conn.execute("DELETE FROM conversations WHERE id = ? AND user_id = ?", (chat_id, user_id)).rowcount
		if rows <= 0:
			raise HTTPException(status_code=404)

def set_file_meta(file_id: str, original: str, chat_id: str):
	with _get_db() as conn:
		conn.execute("INSERT INTO uploads (filename, original, chat_id) VALUES (?, ?, ?)", (file_id, original, chat_id))

def get_file_original_name(file_id: str):
	with _get_db() as conn:
		return conn.execute("SELECT original FROM uploads WHERE filename = ?", (file_id,)).fetchone()

def get_user_info(user_id: str):
	with _get_db() as conn:
		user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
		if user:
			return json.loads(user["settings"] or "{}") | {"name": user["name"], "email": user["email"]}
		raise HTTPException(status_code=401)

_init()
