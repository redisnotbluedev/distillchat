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
def _get_db() -> Iterator[sqlite3.Connection]:
	def parse_timestamp(b):
		dt = datetime.datetime.fromisoformat(b.decode())
		if dt.tzinfo is None:
			return dt.replace(tzinfo=datetime.timezone.utc)
		return dt.astimezone(datetime.timezone.utc)

	sqlite3.register_converter("TIMESTAMP", parse_timestamp)
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

@contextmanager
def transaction():
	with _get_db() as conn:
		yield conn

def _get_hasher():
	return PasswordHash.recommended()

class SkipChat(Exception): ...

def _init():
	with _get_db() as conn:
		conn.executescript("""
			CREATE TABLE IF NOT EXISTS users (
				id TEXT PRIMARY KEY,
				email TEXT UNIQUE NOT NULL,
				password_hash TEXT NOT NULL,
				onboarding_completed BOOLEAN DEFAULT FALSE,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				name TEXT NOT NULL DEFAULT "User",
				settings TEXT NOT NULL DEFAULT "{}"
			);

			CREATE TABLE IF NOT EXISTS conversations (
				id TEXT PRIMARY KEY,
				user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				title TEXT NOT NULL DEFAULT "Untitled",
				public INTEGER NOT NULL DEFAULT 0,
				project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS projects (
				id TEXT PRIMARY KEY,
				user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
				title TEXT NOT NULL DEFAULT "Untitled",
				description TEXT,
				memory TEXT,
				instructions TEXT,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
				updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS project_uploads (
				id TEXT PRIMARY KEY,
				project_id TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
				mime_type TEXT NOT NULL DEFAULT "application/octet-stream",
				original TEXT NOT NULL
			);

			CREATE TABLE IF NOT EXISTS messages (
				id TEXT PRIMARY KEY,
				conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
				parent_id TEXT REFERENCES messages(id),
				role TEXT NOT NULL,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS content_blocks (
				id TEXT PRIMARY KEY,
				message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
				type TEXT NOT NULL,
				content TEXT,
				tool_name TEXT,
				tool_call_id TEXT,
				order_index INTEGER NOT NULL,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS attachments (
				id TEXT PRIMARY KEY,
				message_id TEXT NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
				file_id TEXT NOT NULL REFERENCES uploads(filename) ON DELETE CASCADE,
				created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
			);

			CREATE TABLE IF NOT EXISTS uploads (
				filename TEXT PRIMARY KEY,
				original TEXT NOT NULL,
				mime_type TEXT NOT NULL DEFAULT "application/octet-stream",
				chat_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE
			);

			CREATE INDEX IF NOT EXISTS idx_conversations_user_id ON conversations(user_id);
			CREATE INDEX IF NOT EXISTS idx_messages_conversation_id ON messages(conversation_id);
			CREATE INDEX IF NOT EXISTS idx_content_blocks_message_id ON content_blocks(message_id);
			CREATE INDEX IF NOT EXISTS idx_attachments_message_id ON attachments(message_id);
			CREATE INDEX IF NOT EXISTS idx_uploads_chat_id ON uploads(chat_id);
			CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
			CREATE INDEX IF NOT EXISTS idx_conversations_project_id ON conversations(project_id);
			CREATE INDEX IF NOT EXISTS idx_project_uploads_project_id ON project_uploads(project_id);

			PRAGMA journal_mode=WAL;
			PRAGMA foreign_keys=ON;
		""")
		try:
			conn.execute("ALTER TABLE uploads ADD COLUMN mime_type TEXT NOT NULL DEFAULT 'application/octet-stream'")
		except sqlite3.OperationalError:
			pass

def get_user_id(request: Request) -> str | None:
	token = request.cookies.get("access_token")
	if not token:
		return None

	try:
		payload = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
		return payload.get("user_id")
	except jwt.PyJWTError:
		return None

def check_user(email: str, password: str, user_id: str | None = None):
	with _get_db() as conn:
		if user_id:
			user = conn.execute("SELECT * FROM users WHERE email = ? AND id = ?", (email, user_id)).fetchone()
		else:
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

def get_chats(user_id: str, limit=20, offset=0, query: str | None = None):
	with _get_db() as conn:
		if query:
			return conn.execute(
				"SELECT *, COUNT(*) OVER() AS total_count FROM conversations WHERE user_id = ? AND title LIKE ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
				(user_id, f"%{query}%", limit, offset)
			).fetchall()
		return conn.execute(
			"SELECT *, COUNT(*) OVER() AS total_count FROM conversations WHERE user_id = ? ORDER BY updated_at DESC LIMIT ? OFFSET ?",
			(user_id, limit, offset)
		).fetchall()

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

def get_messages(user_id: str, chat_id: str):
	with _get_db() as conn:
		chat = conn.execute("SELECT * FROM conversations WHERE id = ?", (chat_id,)).fetchone()
		if chat is None:
			raise HTTPException(status_code=404)
		if chat["user_id"] != user_id:
			raise HTTPException(status_code=403)

		# 1. Fetch all messages
		messages = conn.execute("SELECT * FROM messages WHERE conversation_id = ? ORDER BY created_at ASC", (chat_id,)).fetchall()
		if not messages:
			return []

		msg_ids = [msg["id"] for msg in messages]
		placeholders = ",".join("?" * len(msg_ids))

		# 2. Fetch all blocks for all messages in the chat
		blocks = conn.execute(
			f"SELECT * FROM content_blocks WHERE message_id IN ({placeholders}) ORDER BY order_index ASC",
			msg_ids
		).fetchall()

		# 3. Fetch all attachments for all messages in the chat
		attachments = conn.execute(
			f"""
			SELECT a.*, u.original, u.mime_type
			FROM attachments a
			JOIN uploads u ON a.file_id = u.filename
			WHERE a.message_id IN ({placeholders})
			""",
			msg_ids
		).fetchall()

		# Map blocks and attachments to messages
		blocks_by_msg = {}
		for b in blocks:
			blocks_by_msg.setdefault(b["message_id"], []).append(dict(b))

		attach_by_msg = {}
		for a in attachments:
			attach_by_msg.setdefault(a["message_id"], []).append(dict(a))

		result = []
		for msg in messages:
			msg_dict = dict(msg)
			msg_dict["blocks"] = blocks_by_msg.get(msg["id"], [])
			msg_dict["attachments"] = attach_by_msg.get(msg["id"], [])
			result.append(msg_dict)
		return result

def add_message(user_id: str, chat_id: str, role: str, parent_id: str | None = None, message_id: str | None = None):
	with _get_db() as conn:
		chat = conn.execute("SELECT * FROM conversations WHERE id = ?", (chat_id,)).fetchone()
		if chat is None:
			raise HTTPException(status_code=404)
		if chat["user_id"] != user_id:
			raise HTTPException(status_code=403)

		if parent_id is None:
			last_msg = conn.execute(
				"SELECT id FROM messages WHERE conversation_id = ? ORDER BY created_at DESC LIMIT 1",
				(chat_id,)
			).fetchone()
			parent_id = last_msg["id"] if last_msg else None

		id = message_id or str(uuid4())
		conn.execute(
			"INSERT INTO messages (id, conversation_id, parent_id, role) VALUES (?, ?, ?, ?)",
			(id, chat_id, parent_id, role)
		)
		conn.execute("UPDATE conversations SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (chat_id,))
		return id

def add_content_block(message_id: str, type: str, content: str | None = None, tool_name: str | None = None, tool_call_id: str | None = None, order_index: int = 0, block_id: str | None = None):
	with _get_db() as conn:
		id = block_id or str(uuid4())
		conn.execute(
			"INSERT INTO content_blocks (id, message_id, type, content, tool_name, tool_call_id, order_index) VALUES (?, ?, ?, ?, ?, ?, ?)",
			(id, message_id, type, content, tool_name, tool_call_id, order_index)
		)
		return id

def add_attachment(message_id: str, file_id: str):
	with _get_db() as conn:
		id = str(uuid4())
		conn.execute("INSERT INTO attachments (id, message_id, file_id) VALUES (?, ?, ?)", (id, message_id, file_id))
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

def set_file_meta(file_id: str, original: str, chat_id: str, mime_type: str):
	with _get_db() as conn:
		conn.execute("INSERT INTO uploads (filename, original, chat_id, mime_type) VALUES (?, ?, ?, ?)", (file_id, original, chat_id, mime_type))

def get_file_original_name(file_id: str):
	with _get_db() as conn:
		row = conn.execute("SELECT original FROM uploads WHERE filename = ?", (file_id,)).fetchone()
		return row["original"] if row else None

def get_file_meta(file_id: str):
	with _get_db() as conn:
		row = conn.execute("SELECT * FROM uploads WHERE filename = ?", (file_id,)).fetchone()
		return dict(row) if row else None

def get_user_info(user_id: str):
	with _get_db() as conn:
		user = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
		if user:
			return json.loads(user["settings"] or "{}") | {"name": user["name"], "email": user["email"], "created_at": user["created_at"]}
		raise HTTPException(status_code=401)

def update_settings(user_id: str, **kwargs):
	with _get_db() as conn:
		if kwargs.get("created_at"): kwargs.pop("created_at")
		if kwargs.get("email"): kwargs.pop("email")
		conn.execute("UPDATE users SET name = ?, settings = ? WHERE id = ?", (kwargs.pop("name"), json.dumps(kwargs), user_id))

def delete_account(user_id: str):
	with _get_db() as conn:
		conn.execute("DELETE FROM users WHERE id = ?", (user_id,))

def import_chat(user_id: str, name: str, created_at: str, updated_at: str, conn=None):
	id = str(uuid4())
	run = lambda c: c.execute("INSERT INTO conversations (id, user_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (id, user_id, name, created_at, updated_at))
	if conn:
		run(conn)
	else:
		with _get_db() as c:
			run(c)
	return id

def import_message(conversation_id: str, id: str, parent_id: str | None, role: str, created_at: str, conn=None):
	run = lambda c: c.execute("INSERT INTO messages (id, conversation_id, parent_id, role, created_at) VALUES (?, ?, ?, ?, ?)", (id, conversation_id, parent_id, role, created_at))
	if conn:
		run(conn)
	else:
		with _get_db() as c:
			run(c)

def import_block(message_id: str, type: str, content: str, tool_name: str | None, tool_call_id: str | None, order_index: int, created_at: str, conn=None):
	run = lambda c: c.execute("INSERT INTO content_blocks (id, message_id, type, content, tool_name, tool_call_id, order_index, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", (str(uuid4()), message_id, type, content, tool_name, tool_call_id, order_index, created_at))
	if conn:
		run(conn)
	else:
		with _get_db() as c:
			run(c)

def import_attachment(message_id: str, filename: str, original: str, chat_id: str, mime_type: str, created_at: str, conn=None):
	def run(c):
		c.execute("INSERT OR IGNORE INTO uploads (filename, original, chat_id, mime_type) VALUES (?, ?, ?, ?)", (filename, original, chat_id, mime_type))
		c.execute("INSERT INTO attachments (id, message_id, file_id, created_at) VALUES (?, ?, ?, ?)", (str(uuid4()), message_id, filename, created_at))

	if conn:
		run(conn)
	else:
		with _get_db() as c:
			run(c)

def complete_onboarding(user_id: str):
	with _get_db() as conn:
		conn.execute("UPDATE users SET onboarding_completed = TRUE WHERE id = ?", (user_id,))

def has_onboarded(user_id: str):
	with _get_db() as conn:
		return conn.execute("SELECT onboarding_completed FROM users WHERE id = ?", (user_id,)).fetchone()["onboarding_completed"]

def get_projects(user_id: str):
	with _get_db() as conn:
		return conn.execute("SELECT * FROM projects WHERE user_id = ?", (user_id,)).fetchall()

def create_project(user_id: str, name: str, description: str):
	with _get_db() as conn:
		id = str(uuid4())
		conn.execute("INSERT INTO projects (id, user_id, title, description) VALUES (?, ?, ?, ?)", (id, user_id, name, description))
		return id

def get_project(user_id: str, project_id: str):
	with _get_db() as conn:
		meta = conn.execute("SELECT * FROM projects WHERE user_id = ? AND id = ?", (user_id, project_id)).fetchone()
		chats = conn.execute("SELECT * FROM conversations WHERE user_id = ? AND project_id = ?", (user_id, project_id)).fetchall()
		uploads = conn.execute("SELECT * FROM project_uploads WHERE project_id = ?", (project_id,)).fetchall()
		return {"meta": meta, "chats": chats, "uploads": uploads}

def edit_project(user_id: str, project_id: str, name: str, description: str):
	with _get_db() as conn:
		conn.execute("UPDATE projects SET title = ?, description = ? WHERE user_id = ? AND id = ?", (name, description, user_id, project_id))

def delete_project(user_id: str, project_id: str):
	with _get_db() as conn:
		conn.execute("DELETE FROM projects WHERE user_id = ? AND id = ?", (user_id, project_id))

_init()
