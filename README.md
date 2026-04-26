# DistillChat

A fast and lightweight AI chat app that doesn't compromise on aesthetics. 
DistillChat is a self-hosted, open-source chat UI, similar to OpenWebUI, that draws inspiration from the Claude web UI but works with any AI. It uses vanilla HTML5: no React bloat, no lag and DEFINITELY no gigabyte RAM usage.

## Features & Roadmap

- [x] Accounts
	- [x] Login
	- [x] Signup 
- [x] Conversational AI
- [x] Text input
- [x] File input
	- [x] File selecting
	- [x] Drag-and-drop
	- [x] Paste -> attach
- [x] Text output
- [ ] Tools
	- [ ] Select which tools are allowed
	- [ ] MCP server support
	- [x] Show tool calls
- [x] Streaming responses
- [x] Autoscrolling
- [x] Markdown support
- [x] Code highlighting
- [x] Message bubbles
- [x] Sidebar
	- [x] "New chat" button
	- [x] Search chats
	- [x] Chat list
- [x] Branching
- [x] Automatic naming of chats
- [x] Renaming chats
- [x] Deleting chats
- [x] Regenerate responses
- [x] Edit messages
	- [x] User
	- [ ] AI
- [x] Copy message
- [x] Stop generation
- [x] Loading indicator
- [ ] Settings
	- [ ] Language
	- [x] System prompt
	- [ ] Personality
	- [x] User's name
	- [x] Themes
	- [x] fonts
- [x] Import data
- [x] Export data
- [x] Delete account
- [ ] Sharing chats
- [x] Selecting the model
- [ ] Memory
	- [ ] User memory
	- [ ] Project memory
- [x] Projects
- [ ] Artefacts
- [ ] Forms/quizzes
- [ ] Trip planning
- [ ] Recipes
- [x] Error handling
- [ ] Starring/pinning
	- [ ] Chats
	- [ ] Projects

## Installation

1. Copy .env.example to .env and fill out the placeholders.
2. Create a venv:
```bash
# For Linux/MacOS:
python3 -m venv .venv
source .venv/bin/activate
# For Windows:
python -m venv .venv
.\venv\Scripts\activate.bat
```
3. Install the requirements: 
```bash
pip install -r requirements.txt
```
4. Run it
```bash
uvicorn app:app --reload
```
