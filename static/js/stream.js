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
	let timeline = null;
	let timelineDetails = null;
	let contentMarkdown = "";

	const logo = document.createElement("img");
	logo.className = "logo";
	logo.src = "/static/images/logo_loading.svg";
	logo.ariaHidden = "true";

	messageContainer.querySelectorAll(".logo").forEach(l => { l.classList.add("hidden-logo"); });

	messageElement.innerHTML = "";
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

				if (data.type !== lastEvent && data.type !== "ToolResultEvent") {
					element = null;
					text = "";
				}

				switch (data.type) {
					case "MessageCreated":
						messageElement.dataset.id = data.id;
						break;
					case "ContentBlockCreated":
						break;
					case "UserMessageCreated":
						if (userMessage) {
							userMessage.dataset.id = data.id;
							messageElement.dataset.parentId = data.id;
							const existingToolbar = userMessage.querySelector("menu");
							if (existingToolbar) existingToolbar.remove();
							userMessage.appendChild(renderToolbar(userMessage, data.id));
						}
						break;
					case "TokenEvent":
						if (timeline) {
							const action = document.createElement("div");
							action.className = "icon";
							action.innerHTML = icon("circle-check");
							timeline.appendChild(action);

 							const textElement = document.createElement("div");
							textElement.innerHTML = "<p>Done</p>";
							timeline.appendChild(textElement);

							timeline = null;
						}
						if (lastEvent !== "TokenEvent") {
							element = document.createElement("div");
							logo.src = "/static/images/logo_generating.svg";
							logo.before(element);
						}

						text += data.content;
						contentMarkdown += data.content;
						element.innerHTML = marked.parse(text).trim();

						break;
					case "ReasoningEvent": {
						if (!timeline) {
							const details = document.createElement("details");
							details.innerHTML = `<summary>Thinking ${icon("chevron-right")}</summary>`;
							timelineDetails = details.querySelector("summary");

							timeline = document.createElement("div");
							timeline.className = "timeline";
							details.appendChild(timeline);
							logo.before(details);
						} else if (lastEvent !== "ReasoningEvent") {
							timelineDetails.innerHTML = `Thinking ${icon("chevron-right")}`
						}

						if (lastEvent !== "ReasoningEvent") {
							const action = document.createElement("div");
							action.className = "icon";
							action.innerHTML = icon("timer");
							timeline.appendChild(action);

							element = document.createElement("div");
							element.className = "content";
							timeline.appendChild(element);
						}

						logo.src = "/static/images/logo_generating.svg";

						text += data.content;
						element.innerHTML = marked.parse(text).trim();

						break;
					}

					case "ToolStartEvent": {
						if (!timeline) {
							const details = document.createElement("details");
							details.innerHTML = `<summary>Using a tool ${icon("chevron-right")}</summary>`;
							timelineDetails = details.querySelector("summary");

							timeline = document.createElement("div");
							timeline.className = "timeline";
							details.appendChild(timeline);
							logo.before(details);
						} else {
							timelineDetails.innerHTML = `Using a tool ${icon("chevron-right")}`
						}

						const action = document.createElement("div");
						action.className = "icon";
						action.innerHTML = icon("settings");
						timeline.appendChild(action);

						const tool = document.createElement("details");
						timeline.appendChild(tool);
						tool.innerHTML = `
							<summary>Used ${data.name}</summary>
							<div>
								<figure class="code">
									<figcaption>
										<span>json</span>
									</figcaption>
									<pre><code class="hljs language-json">${hljs.highlight(data.arguments, { language: "json", ignoreIllegals: true }).value}</code></pre>
								</figure>
							</div>`;
						element = tool.querySelector("div");

						logo.src = "/static/images/logo_tool.svg";

						break;
					}
					case "ToolResultEvent": {
						if (timeline) {
							const result = document.createElement("figure");
							result.className = "code";
							result.innerHTML = `<figcaption><span>Output</span></figcaption><pre><code>${data.result}</code></pre>`;
							element.appendChild(result);
						}

						break;
					}
					case "ToolEndEvent":
						break;
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
		if (messageElement.dataset.id) {
			state.messageMarkdown[messageElement.dataset.id] = contentMarkdown.trim();
		}
		if (element) {
			element.innerHTML = marked.parse(contentMarkdown.trim());
		}
		logo.before(renderToolbar(messageElement, messageElement.dataset.id));

		const isAtBottom = messageScroll.scrollTop + messageScroll.clientHeight >= messageScroll.scrollHeight - 20;
		if (isAtBottom) {
			messageScroll.scrollTo({
				top: messageScroll.scrollHeight,
				behavior: "instant"
			});
		}
	}
}

export function renderToolbar(messageElement, id) {
	// This is ONLY used in streams. As such, there are assumptions, like how the date is the current time.
	if (id) messageElement.dataset.id = id;
	const date = new Date();
	const tools = document.createElement("menu");

	// Chaos incarnate
	tools.innerHTML = `
		${messageElement.classList.contains("user") ? `
		<li><time data-tooltip="${
		date.toLocaleString(undefined, {month: "long", day: "numeric", year: "numeric", hour: "numeric", minute: "numeric", hour12: true})
		}">${date.toLocaleString(undefined, { month: "short", day: "numeric" })}</time></li>
		<li><button data-tooltip="Edit" onclick="editMessage(this)">${icon("pencil")}</button></li>` : ""}
		<li><button data-tooltip="Copy" onclick="copyMessage(this)">${icon("copy")}</button></li>
		${messageElement.classList.contains("assistant") ? `
		<li><button data-tooltip="Retry" onclick="regenerateMessage(this)">${icon("rotate-cw")}</button></li>` : ""}
	`;

	return tools
}
