/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { state } from "./state.js";
import { showToast } from "./toasts.js";
import { renderAttachment } from "./attachments.js";
import { streamResponse } from "./stream.js";
import { renderMessages } from "./messages.js";
import { marked } from "./marked.js";
import { icon } from "./utils.js";

const attachmentContainer = document.getElementById("attachments");
const renameModal = document.getElementById("renameModal");
const deleteModal = document.getElementById("deleteModal");
const detailsModal = document.getElementById("project-details-modal")
const projectDeleteModal = document.getElementById("project-delete-modal");
const messageContainer = document.getElementById("messages");
const chatInput = document.getElementById("chatInput");
const sendButton = document.getElementById("sendButton");
let selectedChat = null;

async function onInputSubmit() {
	if (state.isStreaming) {
		state.abortController?.abort();
		return;
	}

	if (isNewChat) {
		sendButton.disabled = true;
		const data = new FormData();
		data.append("message", chatInput.value.trim());
		Object.values(state.uploads).forEach(f => { data.append("files", f); })

		if (typeof project !== "undefined") {
			data.append("project", project);
		}

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
		const message = chatInput.value.trim();
		chatInput.value = "";
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

		state.uploads = {};
		attachmentContainer.innerHTML = "";

		state.isStreaming = true;
		sendButton.disabled = true;
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
				state.isStreaming = false;
				sendButton.disabled = false;
				throw new Error((await response.json()).detail);
			}
		}).catch(e => {
			state.isStreaming = false;
			sendButton.disabled = false;
			if (e.name !== "AbortError") showToast("error", `Failed to send message: ${e}`);
		});
	}
}

if (onChatPage) {
	chatInput.addEventListener("input", event => {
		const shouldDisable = event.target.value.trim() === "" && Object.keys(state.uploads).length === 0;
		if (!state.isStreaming) sendButton.disabled = shouldDisable;
	});

	chatInput.addEventListener("keydown", async event => {
		if (event.key === "Enter" && !event.shiftKey && !sendButton.disabled && !state.isStreaming) {
			event.preventDefault();
			await onInputSubmit();
		}
	});

	sendButton.addEventListener("click", onInputSubmit);
}

document.addEventListener("click", event => {
	const pinButton = event.target.closest("menu button:is(.pin, .unpin, .project-unpin)");
	if (pinButton) {
		const pin = pinButton.className === "pin";
		const pinContainer = document.getElementById("pinned");
		const isProject = pinButton.className === "project-unpin";
		selectedChat = pinButton.closest("li:has(> menu)") || pinButton.closest(".chat-header:has(> menu)");
		const id = selectedChat.querySelector(`a:is([href^="/chat"], [href^="/project"])`).href.split("/").pop();

		if (selectedChat.className === "chat-header") {
			event.target.closest("menu").hidePopover();
			selectedChat = document.querySelector("li:has(a.selected)");
		}
		selectedChat.classList.toggle("fade-out", true);
		fetch(`/api/${isProject ? "project" : "chats"}/${id}${isProject ? "/pinned" : ""}`, {
			method: isProject ? "POST" : "PATCH",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ pinned: pin })
		}).then(response => {
			if (response.ok) {
				const done = () => {
					selectedChat.classList.toggle("fade-out", false);
					selectedChat.remove();
					if (!isProject) {
						(pin ? pinContainer : document.getElementById("chats")).prepend(selectedChat);
						const button = selectedChat.querySelector("menu > li > :is(.pin, .unpin)");
						button.innerHTML = pin ? `${icon("pin-off")} Unpin` : `${icon("pin")} Pin`;
						button.className = pin ? "unpin" : "pin";
					}
					if (pin) {
						pinContainer.hidden = false;
					} else {
						if (pinContainer.childElementCount === 0) { pinContainer.hidden = true; }
					}

					if (typeof chatID !== "undefined" && id === chatID) {
						const button = document.querySelector(".chat-header > menu > li > button:is(.pin, .unpin)")
						button.innerHTML = pin ? `${icon("pin-off")} Unpin` : `${icon("pin")} Pin`;
						button.className = pin ? "unpin" : "pin";
					} else if (typeof project !== "undefined" && id === project) {
						const button = document.querySelector(".project button#unpin");
						button.innerHTML = icon("pin");
						button.id = "pin";
					}
				};

				if (selectedChat.getAnimations().some(animation => animation.playState !== "finished")) {
					selectedChat.addEventListener("transitionend", done, { once: true });
				} else {
					done();
				}
			} else {
				showToast("error", `Failed to ${pin ? "pin" : "unpin"} chat: Error ${response.status}`);
			}
		});
		return;
	}

	const renameButton = event.target.closest("menu button.rename");
	if (renameButton) {
		selectedChat = renameButton.closest("li:has(> menu)") || renameButton.closest(".chat-header:has(> menu)");
		renameModal.querySelector("input[type=text]").value = selectedChat.querySelector(".chat-name").innerText;
		renameModal.showModal();
		return;
	}

	const editButton = event.target.closest("menu button.project-edit");
	if (editButton) {
		const entry = editButton.closest("li:has(> menu)");
		detailsModal.querySelector("form").dataset.id = entry.querySelector(`a[href^="/project"]`).href.split("/").pop();
		detailsModal.querySelector("input").value = entry.querySelector(".chat-name").innerText;
		detailsModal.querySelector("textarea").value = entry.querySelector("template").innerHTML;
		detailsModal.showModal();
		return;
	}

	const deleteButton = event.target.closest("menu button.delete");
	if (deleteButton) {
		selectedChat = deleteButton.closest("li:has(> menu)") || deleteButton.closest(".chat-header:has(> menu)");
		deleteModal.showModal();
		return;
	}

	const projectDelete = event.target.closest("menu button.project-delete");
	if (projectDelete) {
		projectDeleteModal.querySelector("form").dataset.id = projectDelete.closest("li:has(> menu)").querySelector(`a[href^="/project"]`).href.split("/").pop();
		projectDeleteModal.showModal();
		return;
	}
});

renameModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	renameModal.close();
	const data = Object.fromEntries((new FormData(event.target)).entries());
	const id = selectedChat.querySelector(`a[href^="/chat"]`).href.split("/").pop();

	fetch(`/api/chats/${id}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(data)
	}).then(response => {
		if (response.ok) {
			if (id === chatID) {
				document.querySelector("a.chat-name.selected").innerText = data.title;
				document.querySelector(".chat-header > a.chat-name").innerText = data.title;
			} else {
				selectedChat.querySelector(".chat-name").innerText = data.title;
			}
		} else {
			showToast("error", `Failed to rename chat: Error ${response.status}`);
		}
	});
});

deleteModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	deleteModal.close();
	const id = selectedChat.querySelector(`a[href^="/chat"]`).href.split("/").pop();

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

detailsModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	detailsModal.close();
	const data = Object.fromEntries((new FormData(event.target)).entries());
	const id = event.currentTarget.dataset.id;

	fetch(`/api/project/${id}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(data)
	}).then(response => {
		if (response.ok) {
			if (document.querySelector(".project")) {
				document.querySelector(".project > div > div > h1").innerText = data.name;
				document.querySelector(".project > div > div > p").innerText = data.description;
			} else if (document.querySelector(".projects")) {
				document.querySelector(`.projects li > a[href="/project/${id}"] > h4`).innerText = data.name;
				document.querySelector(`.projects li > a[href="/project/${id}"] > .description`).innerText = data.description;
			}

			document.querySelector(`nav.chats li > a[href="/project/${id}"]`).innerText = data.name;
			document.querySelector(`nav.chats li > a[href="/project/${id}"] ~ template`).innerHTML = data.description;
		} else {
			showToast("error", `Failed to edit details: Error ${response.status}`);
		}
	});
});

projectDeleteModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	projectDeleteModal.close();
	const id = event.currentTarget.dataset.id;

	fetch(`/api/project/${id}`, {
		method: "DELETE"
	}).then(response => {
		if (response.ok) {
			if (document.querySelector(".project")) {
				location.href = "/projects";
			} else if (document.querySelector(".projects")) {
				document.querySelector(`.projects li:has(a[href="/project/${id}"])`).remove();
			}

			document.querySelector(`nav.chats li:has(a[href="/project/${id}"])`).remove();
		} else {
			showToast("error", `Failed to delete project: Error ${response.status}`);
		}
	});
});
