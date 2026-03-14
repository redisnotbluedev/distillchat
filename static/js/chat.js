/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

(function () {
	const chatInput = document.getElementById("chatInput");
	const sendButton = document.getElementById("sendButton");
	const filePicker = document.getElementById("filePicker");
	const attachmentContainer = document.getElementById("attachments");
	const dragOverlay = document.getElementById("dragOverlay");
	const messageContainer = document.getElementById("messages");
	const messageScroll = messageContainer?.parentElement;
	const renameModal = document.getElementById("renameModal");
	const modelMenu = document.getElementById("modelMenu");
	const modelPicker = document.getElementById("modelPicker");
	let messageMarkdown = {};
	let isStreaming = false;
	let currentModel = localStorage.getItem("model") || document.querySelector("#modelMenu button.selected").dataset.id;
	let abortController = null;
	let _dragCounter = 0;
	let selectedChat = null;
	let uploads = {};

	function copy(button, text) {
		navigator.clipboard.writeText(text).then(() => {
			button.innerHTML = icon("check");
			setTimeout(() => { button.innerHTML = icon("copy") }, 2000);
		}).catch(error => {
			showToast("error", `Failed to copy: ${error}`);
		});
	}

	function showDragOverlay() {
		dragOverlay.classList.add("active");
	}
	function hideDragOverlay() {
		_dragCounter = 0;
		dragOverlay.classList.remove("active");
	}

	document.addEventListener("dragenter", (e) => {
		if (![...e.dataTransfer?.types || []].includes("Files")) return;
		_dragCounter++;
		showDragOverlay();
	});

	document.addEventListener("dragover", (e) => {
		if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) {
			e.preventDefault();
			showDragOverlay();
		}
	});

	document.addEventListener("dragleave", (e) => {
		if (![...e.dataTransfer?.types || []].includes("Files")) return;
		_dragCounter = Math.max(0, _dragCounter - 1);
		if (_dragCounter === 0) hideDragOverlay();
	});

	document.addEventListener("drop", (e) => {
		if (e.dataTransfer && [...e.dataTransfer.types].includes("Files")) {
			e.preventDefault();
			hideDragOverlay();
			handleFileUpload(e.dataTransfer.files);
		}
	});

	function icon(name) {
		return `<svg width="1em" height="1em"><use href="#icon-${name}"></use></svg>`
	}

	function renderAttachment(file, attachmentKey) {
		const attachment = document.createElement("div");

		if (file.type.startsWith("image/")) {
			const url = URL.createObjectURL(file);
			const content = document.createElement("figure");
			const button = document.createElement("button");
			const image = document.createElement("img");

			image.src = url;
			image.alt = file.name;
			image.onload = () => URL.revokeObjectURL(url);
			button.appendChild(image);
			content.appendChild(button);
			attachment.appendChild(content);
		} else {
			attachment.innerHTML = `<figure><figcaption>${file.name}</figcaption><span>${file.name.split(".").slice(-1)[0].toUpperCase()}</span></figure>`;
		}

		if (attachmentKey) {
			const remove = document.createElement("button");
			remove.innerHTML = icon("x");
			remove.onclick = () => {
				attachment.remove();
				delete uploads[attachmentKey];
				const shouldDisable = chatInput.textContent === "" && Object.keys(uploads).length === 0;
				chatInput.classList.toggle("empty", shouldDisable);
				sendButton.disabled = shouldDisable;
			}
			attachment.appendChild(remove);
		}

		return attachment;
	}

	async function onInputSubmit(event) {
		if (isStreaming) {
			abortController?.abort();
			return;
		}

		if (isNewChat) {
			const data = new FormData();
			data.append("message", chatInput.innerText);
			Object.values(uploads).forEach(f => { data.append("files", f); })

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
				console.log(e);
			});
		} else {
			const message = chatInput.innerText;
			chatInput.innerText = "";
			const event = new Event("input", {
				bubbles: true,
				cancelable: true
			});
			chatInput.dispatchEvent(event); // update the input box

			const userMessage = document.createElement("div");
			userMessage.className = "user";
			if (uploads) {
				const attachments = document.createElement("div");
				attachments.className = "attachments";
				Object.values(uploads).forEach(f => { attachments.appendChild(renderAttachment(f)) })
				userMessage.appendChild(attachments)
			}
			if (message) {
				const content = document.createElement("div");
				content.className = "content";
				content.innerHTML = marked.parse(message);
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

			const data = new FormData();
			data.append("message", message);
			data.append("model", currentModel);
			Object.values(uploads).forEach(f => { data.append("files", f); });

			uploads = {};
			attachmentContainer.innerHTML = "";

			abortController = new AbortController();
			fetch(`/api/chats/${chatID}/send_message`, {
				method: "POST",
				body: data,
				signal: abortController.signal
			}).then(async response => {
				await streamResponse(assistantMessage, response);
			}).catch(e => {
				if (e.name !== "AbortError") console.error(e);
			});
		}
	}

	async function streamResponse(messageElement, response) {
		sendButton.innerHTML = icon("circle-stop");
		sendButton.classList.toggle("streaming", true)
		isStreaming = true;

		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";
		let text = "";
		let lastEvent = null;
		let element = null;
		let contentMarkdown = "";

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
						case "TokenEvent":
							if (lastEvent !== "TokenEvent") {
								element = document.createElement("div");
								element.className = "content";
								messageElement.appendChild(element);
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
								messageElement.appendChild(details);
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
			isStreaming = false;
			abortController = null;

			// fuck this, it doesn't have to be canonical, who cares if it changes on reload
			const id = crypto.randomUUID()
			messageMarkdown[id] = contentMarkdown;
			messageElement.dataset.id = id;

			const tools = document.createElement("menu");
			messageElement.appendChild(tools);
			tools.innerHTML = `
				<li><button onclick="copyMessage(this)">${icon("copy")}</button></li>`;
			const isAtBottom = messageScroll.scrollTop + messageScroll.clientHeight >= messageScroll.scrollHeight - 20;
			if (isAtBottom) {
				messageScroll.scrollTo({
					top: messageScroll.scrollHeight,
					behavior: "instant"
				});
			}
		}
	}

	function handleFileUpload(files) {
		Array.from(files).forEach(f => {
			if (f.size > maxUploadSize) {
				showToast("warning", `You may not upload files larger than ${formatBytes(maxUploadSize)}.`);
				return;
			}
			const key = crypto.randomUUID();
			const attachment = renderAttachment(f, key);
			uploads[key] = f;
			attachmentContainer.appendChild(attachment);

			sendButton.disabled = false;
			chatInput.classList.toggle("empty", false);
		});
	}

	const formatBytes = (bytes, dp = 0) => {
		if (!bytes) return "0 B";
		const i = Math.floor(Math.log(bytes) / Math.log(1024));
		return (bytes / Math.pow(1024, i)).toFixed(dp) + " " + ["B", "KB", "MB", "GB", "TB"][i];
	};

	chatInput.addEventListener("input", event => {
		const shouldDisable = event.target.textContent === "" && Object.keys(uploads).length === 0;
		sendButton.disabled = shouldDisable;
		chatInput.classList.toggle("empty", shouldDisable)
	});
	chatInput.addEventListener("keydown", async event => {
		if (event.key === "Enter" && !event.shiftKey && !sendButton.disabled && !isStreaming) {
			event.preventDefault();
			await onInputSubmit();
		}
	});

	chatInput.addEventListener("paste", e => {
		const items = [...e.clipboardData.items];
		const files = items
			.filter(item => item.kind === "file")
			.map(item => item.getAsFile());

		if (files.length > 0) {
			e.preventDefault();
			handleFileUpload(files);
		}
	});
	filePicker.addEventListener("change", event => {
		handleFileUpload(event.target.files);
  		event.target.value = null;
	});
	sendButton.addEventListener("click", onInputSubmit);

	document.querySelectorAll(".chats menu button.rename").forEach(b => {
		b.addEventListener("click", () => {
			selectedChat = b.closest("li:has(> menu)");
			renameModal.querySelector("input[type=text]").value = selectedChat.querySelector("a").innerText;
			renameModal.showModal();
		});
	});

	document.querySelectorAll(".chats menu button.delete").forEach(b => {
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
				selectedChat.querySelector("a").innerText = data.title;
			} else {
				showToast("error", `Failed to rename chat: Error ${response.status}`);
			}
		});
	});

	deleteModal.querySelector("form").addEventListener("submit", event => {
		event.preventDefault();
		deleteModal.close();
		const id = selectedChat.querySelector("a").href.split("/").pop();

		fetch(`/api/chats/${id}`, {
			method: "DELETE"
		}).then(response => {
			if (response.ok) {
				selectedChat.remove();
				if (chatID === id) {
					location.href = "/";
				} else {
					console.log(chatID);
					console.log(id);
				}
			} else {
				showToast("error", `Failed to delete chat: Error ${response.status}`);
			}
		});
	});

	modelMenu.querySelectorAll("button").forEach(button => {
		button.addEventListener("click", e => {
			modelMenu.hidePopover();
			currentModel = button.dataset.id;
			localStorage.setItem("model", currentModel);
			modelMenu.querySelectorAll("button.selected").forEach(b => { b.classList.toggle("selected", false) })
			button.classList.toggle("selected", true);
			modelPicker.innerHTML = `${button.querySelector("h3").innerText} ${icon("chevron-down")}`;
		})
	});

	if (currentModel) {
		modelMenu.querySelectorAll("button.selected").forEach(b => { b.classList.toggle("selected", false) });
		const button = modelMenu.querySelector(`button[data-id="${currentModel}"]`);
		button.classList.toggle("selected", true);
		modelPicker.innerHTML = `${button.querySelector("h3").innerText} ${icon("chevron-down")}`;
	}

	if (!isNewChat) {
		document.querySelector(`aside a[href="/chat/${chatID}"]`).classList.toggle("selected", true)

		if (document.querySelector(".messages > .user:last-child")) {
			const message = document.createElement("div");
			message.className = "assistant";
			messageContainer.appendChild(message);

			fetch(`/api/chats/${chatID}/regenerate`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ "model": currentModel })
			}).then(async response => {
				await streamResponse(message, response);
			}).then(() => {
				fetch(`/api/chats/${chatID}`).then(response => {
					return response.json();
				}).then(data => {
					document.querySelector("nav.chats a.selected").innerText = data.title;
				});
			}).catch(e => {
				console.error(e);
			});
		}

		window.copyCode = button => {
			const code = button.closest("figure.code").querySelector("code").textContent;
			copy(button, code);
		}

		window.copyMessage = button => {
			const id = button.closest("div[data-id]").dataset.id;
			copy(button, messageMarkdown[id].trim());
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

		messageContainer.querySelectorAll(".content").forEach(message => {
			const id = message.closest("div[data-id]").dataset.id;
			messageMarkdown[id] ??= "";
			messageMarkdown[id] += `\n${message.textContent}`;
			message.innerHTML = marked.parse(message.textContent).trim();
		});

		messageContainer.querySelectorAll(".reasoning > blockquote").forEach(message => {
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

		setTimeout(() => messageScroll.scrollTo({ top: messageScroll.scrollHeight }), 20); // Let it render or smth idek but this makes it work better
	}
})();
