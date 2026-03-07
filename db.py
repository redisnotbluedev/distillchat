# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>

import sqlite3, os, jwt
from uuid import uuid4
from pwdlib import PasswordHash
from fastapi import HTTPException, Request
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
			CREATE TABLE IF NOT EXISTS users (
				id TEXT PRIMARY KEY,
				email TEXT UNIQUE NOT NULL,
				password_hash TEXT NOT NULL,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS conversations (
				id TEXT PRIMARY KEY,
				user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				title TEXT NOT NULL DEFAULT "New Conversation",
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS messages (
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

def get_chats(user_id: str):
	with _get_db() as conn:
		chats = conn.execute("SELECT * FROM conversations WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall()
		return chats

def create_chat(user_id: str, initial_message: str):
	try:
		with _get_db() as conn:
			id = str(uuid4())
			conn.execute("INSERT INTO conversations (id, user_id) VALUES (?, ?)", (id, user_id))
			conn.execute("INSERT INTO messages (id, conversation_id, role, content) VALUES (?, ?, ?, ?)", (str(uuid4()), id, "user", initial_message))
			return id
	except sqlite3.IntegrityError as e:
		if getattr(e, "sqlite_errorname", None) == "SQLITE_CONSTRAINT_FOREIGNKEY":
			return None
		else:
			raise

def get_messages(user_id: str, chat_id: str):
	with _get_db() as conn:
		chat = conn.execute("SELECT * FROM conversations WHERE id = ?", (chat_id,)).fetchone()
		if chat is None:
			raise HTTPException(status_code=404)
		if chat["user_id"] != user_id:
			raise HTTPException(status_code=403)

		return conn.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC", (chat_id,)).fetchall()

def add_message(user_id: str, chat_id: str, content: str, role: str, type: str = "text", tool_name: str = None, tool_call_id: str = None):
	with _get_db() as conn:
		chat = conn.execute("SELECT * FROM conversations WHERE id = ?", (chat_id,)).fetchone()
		if chat is None:
			raise HTTPException(status_code=404)
		if chat["user_id"] != user_id:
			raise HTTPException(status_code=403)

		# Find the most recent message to set as the parent
		last_message = conn.execute(
			"SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
			(chat_id,)
		).fetchone()
		parent_id = last_message["id"] if last_message else None

		id = str(uuid4())
		conn.execute(
			"INSERT INTO messages (id, conversation_id, parent_id, role, content, type, tool_name, tool_call_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
			(id, chat_id, parent_id, role, content, type, tool_name, tool_call_id)
		)
		conn.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
		return id

_init()
