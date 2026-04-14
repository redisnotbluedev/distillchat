/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { state } from "./state.js";
import { icon, copy } from "./utils.js";
import { streamResponse, renderToolbar } from "./stream.js";
import { showToast } from "./toasts.js";

const messageContainer = document.getElementById("messages");
const messageScroll = messageContainer?.parentElement;

export function renderMessages() {
	function findLeaf(node) {
		const child = messageContainer.querySelector(`:scope > div[data-parent-id="${node.dataset.id}"]`);
		return child ? findLeaf(child) : node;
	}

	messageContainer.querySelectorAll(":scope > div").forEach(m => { m.hidden = true; });
	messageContainer.querySelectorAll(".logo").forEach(l => { l.classList.add("hidden-logo"); });

	let currentBranch = state.currentLeaf;
	if (currentBranch?.classList.contains("assistant")) {
		currentBranch.querySelectorAll(".logo").forEach(l => { l.classList.remove("hidden-logo"); });
	}

	while ((currentBranch?.dataset?.parentId || "None") !== "None") {
		currentBranch.hidden = false;
		const allSiblings = Array.from(messageContainer.querySelectorAll(`:scope > div[data-parent-id="${currentBranch.dataset.parentId}"]`));
		const idx = allSiblings.indexOf(currentBranch);
		const total = allSiblings.length;

		if (total > 1) {
			const toolbar = currentBranch.querySelector("menu:last-of-type");
			toolbar.querySelectorAll("li.branches").forEach(e => e.remove());

			const leftBranch = document.createElement("li");
			const leftButton = document.createElement("button");
			leftBranch.className = "branches";
			leftButton.innerHTML = icon("chevron-left");
			leftButton.disabled = idx === 0;
			leftButton.addEventListener("click", () => {
				state.currentLeaf = findLeaf(allSiblings[idx - 1]);
				renderMessages();
			});
			leftBranch.appendChild(leftButton);
			toolbar.appendChild(leftBranch);

			const display = document.createElement("li");
			display.className = "branches display";
			display.innerText = `${idx + 1}/${total}`;
			toolbar.appendChild(display);

			const rightBranch = document.createElement("li");
			const rightButton = document.createElement("button");
			rightBranch.className = "branches";
			rightButton.disabled = idx === total - 1;
			rightButton.innerHTML = icon("chevron-right");
			rightButton.addEventListener("click", () => {
				state.currentLeaf = findLeaf(allSiblings[idx + 1]);
				renderMessages();
			});
			rightBranch.appendChild(rightButton);
			toolbar.appendChild(rightBranch);
		}

		currentBranch = messageContainer.querySelector(`:scope > div[data-id="${currentBranch.dataset.parentId}"]`);
	}
	if (currentBranch) currentBranch.hidden = false;
}

export function initMessages() {
	window.copyCode = button => {
		const code = button.closest("figure.code").querySelector("code").textContent;
		copy(button, code);
	}

	window.copyMessage = button => {
		const id = button.closest("div[data-id]").dataset.id;
		copy(button, state.messageMarkdown[id].trim());
	}

	window.regenerateMessage = button => {
		const oldMessage = button.closest("div[data-id]");
		oldMessage.hidden = true;

		const message = document.createElement("div");
		message.className = "assistant";
		message.dataset.parentId = oldMessage.dataset.parentId;
		messageContainer.appendChild(message);

		state.abortController = new AbortController;

		fetch(`/api/chats/${chatID}/regenerate`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ "model": state.currentModel, "leaf_id": oldMessage.dataset.parentId }),
			signal: state.abortController.signal
		}).then(async response => {
			await streamResponse(message, response);
		}).then(() => {
			state.currentLeaf = message;
			renderMessages();
		}).catch(e => {
			console.error(e);
		});
	}

	window.editMessage = button => {
		if (state.isStreaming) { return }

		const oldUserMessage = button.closest("div[data-id]");
		oldUserMessage.hidden = true;
		let text = oldUserMessage.querySelector(".content").textContent;

		const edit = document.createElement("div");
		edit.className = "user";
		edit.innerHTML = `<div class="edit">
			<div contenteditable="plaintext-only">${text}</div>
			<div class="actions">
				${icon("info")}
				<p>Editing this message will create a new conversation branch. You can switch between branches using the arrow navigation buttons.</p>
				<button class="cancel">Cancel</button>
				<button class="save">Save</button>
			</div>
		</div>`;

		oldUserMessage.after(edit);
		edit.querySelector("button.cancel").addEventListener("click", e => {
			edit.remove();
			oldUserMessage.hidden = false;
		});
		edit.querySelector("button.save").addEventListener("click", e => {
			text = edit.querySelector("div[contenteditable]").innerText.trim();
			edit.remove();

			const data = new FormData();
			oldUserMessage.querySelectorAll(".attachments > div[data-src]").forEach(e => {
				data.append("file_ids", e.dataset.src);
			});

			data.append("message", text);
			data.append("model", state.currentModel);
			data.append("leaf_id", oldUserMessage.dataset.parentId);

			const newUserMessage = document.createElement("div");
			newUserMessage.className = "user";
			newUserMessage.dataset.parentId = oldUserMessage.dataset.parentId;

			const attachments = oldUserMessage.querySelector(".attachments");
			if (attachments) newUserMessage.appendChild(attachments.cloneNode(true));

			const content = document.createElement("div");
			content.className = "content";
			content.innerHTML = marked.parse(text).trim();
			newUserMessage.appendChild(content);

			const assistantMessage = document.createElement("div");
			assistantMessage.className = "assistant";

			const messages = Array.from(messageContainer.children);
			messages.slice(messages.indexOf(oldUserMessage) + 1).forEach(e => { e.hidden = true; })
			
			oldUserMessage.after(newUserMessage);
			newUserMessage.after(assistantMessage);

			messageScroll.scrollTo({
				top: messageScroll.scrollHeight,
				behavior: "smooth"
			});

			state.abortController = new AbortController();
			fetch(`/api/chats/${chatID}/send-message`, {
				method: "POST",
				body: data,
				signal: state.abortController.signal
			}).then(async response => {
				if (response.ok) {
					await streamResponse(assistantMessage, response, newUserMessage);
					state.currentLeaf = assistantMessage;
					state.messageMarkdown[newUserMessage.dataset.id] = text;
					renderMessages();
				} else {
					throw new Error((await response.json()).detail);
				}
			}).catch(e => {
				if (e.name !== "AbortError") showToast("error", `Failed to send message: ${e}`);
			});
		});
	}

	const renderer = {
		code({ text, lang }) {
			const language = lang && hljs.getLanguage(lang) ? lang : "plaintext";
			const highlighted = hljs.highlight(text, { language: language, ignoreIllegals: true }).value;
			return `
			<figure class="code">
				<figcaption>
					<span>${language}</span>
					<button data-tooltip="Copy" onclick="copyCode(this)">
						${icon("copy")}
					</button>
				</figcaption>
				<pre><code class="hljs language-${language}">${highlighted}</code></pre>
			</figure>`;
		}
	}
	marked.use({ renderer })

	messageContainer.querySelectorAll(".messages > div > .content").forEach(message => {
		const id = message.closest("div[data-id]").dataset.id;
		const text = message.textContent.trim();
		state.messageMarkdown[id] = text;
		message.innerHTML = marked.parse(text).trim();
	});

	messageContainer.querySelectorAll(".assistant > details .content").forEach(message => {
		message.innerHTML = marked.parse(message.textContent.trim()).trim();
	});

	messageContainer.querySelectorAll("menu time").forEach(time => {
		const date = new Date(time.dateTime);
		const isSameYear = date.getFullYear() === new Date().getFullYear();

		time.innerText = date.toLocaleString(undefined, {
			month: "short",
			day: "numeric",
			year: isSameYear ? undefined : "numeric"
		});
		time.closest("li").dataset.tooltip = date.toLocaleString(undefined, {
			month: "long",
			day: "numeric",
			year: "numeric",
			hour: "numeric",
			minute: "numeric",
			hour12: true
		});
	});

	document.querySelector(`aside a[href="/chat/${chatID}"]`).classList.toggle("selected", true);
	renderMessages();

	if (document.querySelector(".messages > .user:last-child")) {
		const message = document.createElement("div");
		message.className = "assistant";
		messageContainer.appendChild(message);

		fetch(`/api/chats/${chatID}/regenerate`, {
			method: "POST",
			headers: { "Content-Type": "application/json" },
			body: JSON.stringify({ "model": state.currentModel })
		}).then(async response => {
			await streamResponse(message, response);
		}).then(() => {
			message.dataset.parentId = state.currentLeaf.dataset.id;
			state.currentLeaf = message;
			renderMessages();

			fetch(`/api/chats/${chatID}`).then(response => {
				return response.json();
			}).then(data => {
				document.querySelector("nav.chats a.selected").innerText = data.title;
			});
		}).catch(e => {
			console.error(e);
		});
	}

	setTimeout(() => messageScroll.scrollTo({ top: messageScroll.scrollHeight }), 20); // Let it render or smth idek but this makes it work better
}
