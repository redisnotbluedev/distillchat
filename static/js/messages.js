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
	let currentBranch = state.currentLeaf;
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
			message.dataset.parentId = oldMessage.dataset.parentId;
			state.currentLeaf = message;
			renderMessages();
		}).catch(e => {
			console.error(e);
		});
	}

	window.editMessage = button => {
		if (state.isStreaming) { return }

		const message = button.closest("div[data-id]");
		message.hidden = true;
		let text = message.querySelector(".content").textContent;

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

		message.after(edit);
		edit.querySelector("button.cancel").addEventListener("click", e => {
			edit.remove();
			message.hidden = false;
		});
		edit.querySelector("button.save").addEventListener("click", e => {
			text = edit.querySelector("div[contenteditable]").innerText;
			edit.remove();

			const data = new FormData();
			message.querySelectorAll("attachments > div[data-src]").forEach(e => {
				data.append("file_ids", e.dataset.src);
			});

			data.append("message", text);
			data.append("model", state.currentModel);
			data.append("leaf_id", message.dataset.parentId);

			message.innerHTML = `<div class="content">${marked.parse(text)}</div>`;
			message.appendChild(renderToolbar(message));

			const assistantMessage = document.createElement("div");
			assistantMessage.className = "assistant";
			message.hidden = false;

			const messages = Array.from(messageContainer.children);
			messages.slice(messages.indexOf(message) + 1).forEach(e => { e.hidden = true; }) // tried to use querySelectorAll w/ :scope ~ * but that didn't work..
			message.after(assistantMessage);

			messageScroll.scrollTo({
				top: messageScroll.scrollHeight,
				behavior: "smooth"
			});

			state.abortController = new AbortController();
			fetch(`/api/chats/${chatID}/send_message`, {
				method: "POST",
				body: data,
				signal: state.abortController.signal
			}).then(async response => {
				if (response.ok) {
					await streamResponse(assistantMessage, response, message);
					currentLeaf = assistantMessage;
					state.messageMarkdown[message.dataset.id] = text;
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
		state.messageMarkdown[id] ??= "";
		state.messageMarkdown[id] += `\n${message.textContent}`;
		message.innerHTML = marked.parse(message.textContent).trim();
	});

	messageContainer.querySelectorAll(".assistant > details .content").forEach(message => {
		message.innerHTML = marked.parse(message.textContent).trim();
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
