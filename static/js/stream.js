/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { state } from "./state.js";
import { icon } from "./utils.js";
import { showToast } from "./toasts.js";

const messageContainer = document.getElementById("messages");
const messageScroll = messageContainer?.parentElement;
const sendButton = document.getElementById("sendButton");
const chatInput = document.getElementById("chatInput");

export async function streamResponse(messageElement, response, userMessage = null) {
	sendButton.innerHTML = icon("circle-stop");
	sendButton.classList.toggle("streaming", true)
	sendButton.disabled = false;
	state.isStreaming = true;

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";
	let text = "";
	let lastEvent = null;
	let element = null;
	let contentMarkdown = "";
	let blockID = "";
	const logo = document.createElement("img");

	logo.className = "logo";
	logo.src = "/static/images/logo_loading.svg";
	logo.ariaHidden = true;
	messageElement.appendChild(logo);

	try {
	while (true) {
		const { value, done } = await reader.read();
		if (done) break;

		const chunk = decoder.decode(value, { stream: true });
		const lines = (buffer + chunk).split("\n");
		buffer = lines.pop();

		for (const line of lines) {
			if (line.trim().startsWith("data: ")) {
				const data = JSON.parse(line.trim().slice(6));

				if (data.type !== lastEvent) {
					element = null;
					text = "";
				}

				switch (data.type) {
					case "BlockCreated":
						blockID = data.id;
						break;
					case "UserMessageCreated":
						// Ok so this strictly SHOULDN'T be handled by streamResponse,
						// but look, where else am I meant to get a canonical ID?
						userMessage.dataset.id = data.id;
						messageElement.dataset.parentId = data.id;
						renderToolbar(userMessage, data.id);
						break;
					case "TokenEvent":
						if (lastEvent !== "TokenEvent") {
							element = document.createElement("div");
							element.className = "content";
							logo.src = "/static/images/logo_generating.svg";
							logo.before(element);
						}

						text += data.content;
						contentMarkdown += data.content;
						element.innerHTML = marked.parse(text);

						break;
					case "ReasoningEvent":
						if (lastEvent !== "ReasoningEvent") {
							const details = document.createElement("details");
							details.className = "reasoning";
							const summary = document.createElement("summary");
							summary.innerHTML = `Thinking ${icon("chevron-right")}`;
							element = document.createElement("blockquote");
							details.appendChild(summary);
							details.appendChild(element);
							logo.src = "/static/images/logo_generating.svg";
							logo.before(details);
						}

						text += data.content;
						element.innerHTML = marked.parse(text);

						break;
					// case "ToolStartEvent":
					// 	break;
					// case "ToolEndEvent":
					// 	break;
					default:
						showToast("error", `Unhandled event in input stream: ${data.type}`)
						break;
				}

				const isAtBottom = messageScroll.scrollTop + messageScroll.clientHeight >= messageScroll.scrollHeight - 50;
				if (isAtBottom) {
					messageScroll.scrollTo({
						top: messageScroll.scrollHeight,
						behavior: "instant"
					});
				}
				lastEvent = data.type;
			}
		}
	}
	} catch (e) {
		if (e.name !== "AbortError") throw e;
	} finally {
		sendButton.innerHTML = icon("arrow-up");
		sendButton.classList.toggle("streaming", false);
		state.isStreaming = false;
		state.abortController = null;
		const shouldDisable = chatInput.textContent === "" && Object.keys(state.uploads).length === 0;
		sendButton.disabled = shouldDisable;
		logo.src = "/static/images/logo.png";

		// fuck this, it doesn't have to be canonical, who cares if it changes on reload
		// ^ yeah so that was foreshadowing, this was a really big problem
		// const id = crypto.randomUUID()
		state.messageMarkdown[blockID] = contentMarkdown;
		const toolbar = renderToolbar(messageElement, blockID);
		logo.before(toolbar);
		messageElement.dataset.id = blockID;

		const isAtBottom = messageScroll.scrollTop + messageScroll.clientHeight >= messageScroll.scrollHeight - 20;
		if (isAtBottom) {
			messageScroll.scrollTo({
				top: messageScroll.scrollHeight,
				behavior: "instant"
			});
		}
	}
}

function renderToolbar(messageElement, id) {
	// This is ONLY used in streams. As such, there are assumptions, like how the date is the current time.
	messageElement.dataset.id = id;
	const date = new Date();
	const tools = document.createElement("menu");

	// Chaos incarnate
	tools.innerHTML = `
		${messageElement.classList.contains("user") ? `
		<li><time data-tooltip="${
		date.toLocaleString(undefined, {month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "numeric", hour12: true})
		}">${date.toLocaleString(undefined, { month: "short", day: "numeric" })}</time></li>
		<li><button data-tooltip="Edit" onclick="editMessage(this)">${icon("edit")}</button></li>` : ""}
		<li><button data-tooltip="Copy" onclick="copyMessage(this)">${icon("copy")}</button></li>
		${messageElement.classList.contains("assistant") ? `
		<li><button data-tooltip="Retry" onclick="regenerateMessage(this)">${icon("rotate-cw")}</button></li>` : ""}
	`;

	return tools
}
