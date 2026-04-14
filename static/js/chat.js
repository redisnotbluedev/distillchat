/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { state } from "./state.js";
import { showToast } from "./toasts.js";
import { renderAttachment } from "./attachments.js";
import { streamResponse } from "./stream.js";
import { renderMessages } from "./messages.js";

const attachmentContainer = document.getElementById("attachments");
const renameModal = document.getElementById("renameModal");
const deleteModal = document.getElementById("deleteModal");
const messageContainer = document.getElementById("messages");
const messageScroll = messageContainer?.parentElement;
const chatInput = document.getElementById("chatInput");
const sendButton = document.getElementById("sendButton");
let selectedChat = null;

async function onInputSubmit(event) {
	if (state.isStreaming) {
		state.abortController?.abort();
		return;
	}

	if (isNewChat) {
		const data = new FormData();
		data.append("message", chatInput.innerText.trim());
		Object.values(state.uploads).forEach(f => { data.append("files", f); })

		fetch("/api/chats", {
			method: "POST",
			body: data
		}).then(response => {
			if (response.ok) {
				return response.json();
			} else {
				throw new Error(response.status);
			}
		}).then(data => {
			location.href = `/chat/${data.id}`;
		}).catch(e => {
			console.error(e);
		});
	} else {
		const message = chatInput.innerText.trim();
		chatInput.innerText = "";
		const event = new Event("input", {
			bubbles: true,
			cancelable: true
		});
		chatInput.dispatchEvent(event); // update the input box

		const userMessage = document.createElement("div");
		userMessage.className = "user";
		userMessage.dataset.parentId = state.currentLeaf.dataset.id;

		const data = new FormData();
		data.append("message", message);
		data.append("model", state.currentModel);
		data.append("leaf_id", state.currentLeaf.dataset.id);

		if (state.uploads) {
			const attachments = document.createElement("div");
			attachments.className = "attachments";
			Object.values(state.uploads).forEach(f => { attachments.appendChild(renderAttachment(f)); data.append("files", f); })
			userMessage.appendChild(attachments)
		}
		if (message) {
			const content = document.createElement("div");
			content.className = "content";
			content.innerHTML = marked.parse(message).trim();
			userMessage.appendChild(content)
		}
		messageContainer.appendChild(userMessage);

		const assistantMessage = document.createElement("div");
		assistantMessage.className = "assistant";
		messageContainer.appendChild(assistantMessage);

		messageScroll.scrollTo({
			top: messageScroll.scrollHeight,
			behavior: "smooth"
		})

		state.uploads = {};
		attachmentContainer.innerHTML = "";

		state.abortController = new AbortController();
		fetch(`/api/chats/${chatID}/send-message`, {
			method: "POST",
			body: data,
			signal: state.abortController.signal
		}).then(async response => {
			if (response.ok) {
				await streamResponse(assistantMessage, response, userMessage);
				state.currentLeaf = assistantMessage;
				state.messageMarkdown[userMessage.dataset.id] = message;
				renderMessages();
			} else {
				throw new Error((await response.json()).detail);
			}
		}).catch(e => {
			if (e.name !== "AbortError") showToast("error", `Failed to send message: ${e}`);
		});
	}
}

if (onChatPage) {
	chatInput.addEventListener("input", event => {
		const shouldDisable = event.target.textContent === "" && Object.keys(state.uploads).length === 0;
		sendButton.disabled = shouldDisable;
		chatInput.classList.toggle("empty", shouldDisable)
	});

	chatInput.addEventListener("keydown", async event => {
		if (event.key === "Enter" && !event.shiftKey && !sendButton.disabled && !state.isStreaming) {
			event.preventDefault();
			await onInputSubmit();
		}
	});

	sendButton.addEventListener("click", onInputSubmit);
}

document.querySelectorAll("menu button.rename").forEach(b => {
	b.addEventListener("click", () => {
		selectedChat = b.closest("li:has(> menu)");
		renameModal.querySelector("input[type=text]").value = selectedChat.querySelector(".chat-name").innerText;
		renameModal.showModal();
	});
});

document.querySelectorAll("menu button.delete").forEach(b => {
	b.addEventListener("click", () => {
		selectedChat = b.closest("li:has(> menu)");
		deleteModal.showModal();
	});
});

renameModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	renameModal.close();
	const data = Object.fromEntries((new FormData(event.target)).entries());
	const id = selectedChat.querySelector("a").href.split("/").pop();

	fetch(`/api/chats/${id}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(data)
	}).then(response => {
		if (response.ok) {
			selectedChat.querySelector(".chat-name").innerText = data.title;
		} else {
			showToast("error", `Failed to rename chat: Error ${response.status}`);
		}
	});
});

deleteModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	deleteModal.close();
	const id = selectedChat.querySelector(".chat-name").href.split("/").pop();

	fetch(`/api/chats/${id}`, {
		method: "DELETE"
	}).then(response => {
		if (response.ok) {
			selectedChat.remove();
			if (chatID === id) {
				location.href = "/";
			}
		} else {
			showToast("error", `Failed to delete chat: Error ${response.status}`);
		}
	});
});
