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
	let currentLeaf = messageContainer?.lastElementChild;

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

	function renderMessages() {
		function findLeaf(node) {
			const child = messageContainer.querySelector(`:scope > div[data-parent-id="${node.dataset.id}"]`);
			return child ? findLeaf(child) : node;
		}

		messageContainer.querySelectorAll(":scope > div").forEach(m => { m.hidden = true; });
		let currentBranch = currentLeaf;
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
					currentLeaf = findLeaf(allSiblings[idx - 1]);
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
					currentLeaf = findLeaf(allSiblings[idx + 1]);
					renderMessages();
				});
				rightBranch.appendChild(rightButton);
				toolbar.appendChild(rightBranch);
			}

			currentBranch = messageContainer.querySelector(`:scope > div[data-id="${currentBranch.dataset.parentId}"]`);
		}
		if (currentBranch) currentBranch.hidden = false;
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
		return `<svg viewBox="0 0 24 24"><use href="#icon-${name}"></use></svg>`
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
			data.append("message", chatInput.innerText.trim());
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
			userMessage.dataset.parentId = currentLeaf.dataset.id;

			const data = new FormData();
			data.append("message", message);
			data.append("model", currentModel);
			data.append("leaf_id", currentLeaf.dataset.id);

			if (uploads) {
				const attachments = document.createElement("div");
				attachments.className = "attachments";
				Object.values(uploads).forEach(f => { attachments.appendChild(renderAttachment(f)); data.append("files", f); })
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

			uploads = {};
			attachmentContainer.innerHTML = "";

			abortController = new AbortController();
			fetch(`/api/chats/${chatID}/send_message`, {
				method: "POST",
				body: data,
				signal: abortController.signal
			}).then(async response => {
				if (response.ok) {
					await streamResponse(assistantMessage, response, userMessage);
					currentLeaf = assistantMessage;
					messageMarkdown[userMessage.dataset.id] = message;
					renderMessages();
				} else {
					throw new Error((await response.json()).detail);
				}
			}).catch(e => {
				if (e.name !== "AbortError") showToast("error", `Failed to send message: ${e}`);
			});
		}
	}

	function renderToolbar(messageElement, id) {
		// This is ONLY used in streams. As such, there are assumptions, like how the date is the current time.
		messageElement.dataset.id = id;
		const date = new Date();
		const tools = document.createElement("menu");

		messageElement.appendChild(tools);
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
	}

	async function streamResponse(messageElement, response, userMessage = null) {
		sendButton.innerHTML = icon("circle-stop");
		sendButton.classList.toggle("streaming", true)
		sendButton.disabled = false;
		isStreaming = true;

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
			isStreaming = false;
			abortController = null;
			const shouldDisable = chatInput.textContent === "" && Object.keys(uploads).length === 0;
			sendButton.disabled = shouldDisable;
			logo.src = "/static/images/logo.png";

			// fuck this, it doesn't have to be canonical, who cares if it changes on reload
			// ^ yeah so that was foreshadowing, this was a really big problem
			// const id = crypto.randomUUID()
			messageMarkdown[blockID] = contentMarkdown;
			renderToolbar(messageElement, blockID);
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
		document.querySelector(`aside a[href="/chat/${chatID}"]`).classList.toggle("selected", true);
		renderMessages();

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
				message.dataset.parentId = currentLeaf.dataset.id;
				currentLeaf = message;
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

		window.copyCode = button => {
			const code = button.closest("figure.code").querySelector("code").textContent;
			copy(button, code);
		}

		window.copyMessage = button => {
			const id = button.closest("div[data-id]").dataset.id;
			copy(button, messageMarkdown[id].trim());
		}

		window.regenerateMessage = button => {
			const oldMessage = button.closest("div[data-id]");
			oldMessage.hidden = true;

			const message = document.createElement("div");
			message.className = "assistant";
			messageContainer.appendChild(message);

			abortController = new AbortController;

			fetch(`/api/chats/${chatID}/regenerate`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ "model": currentModel, "leaf_id": oldMessage.dataset.parentId }),
				signal: abortController.signal
			}).then(async response => {
				await streamResponse(message, response);
			}).then(() => {
				message.dataset.parentId = oldMessage.dataset.parentId;
				currentLeaf = message;
				renderMessages();
			}).catch(e => {
				console.error(e);
			});
		}

		window.editMessage = button => {
			if (isStreaming) { return }

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
				data.append("model", currentModel);
				data.append("leaf_id", message.dataset.parentId);

				message.innerHTML = `<div class="content">${marked.parse(text)}</div>`;

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

				abortController = new AbortController();
				fetch(`/api/chats/${chatID}/send_message`, {
					method: "POST",
					body: data,
					signal: abortController.signal
				}).then(async response => {
					if (response.ok) {
						await streamResponse(assistantMessage, response, message);
						currentLeaf = assistantMessage;
						messageMarkdown[message.dataset.id] = text;
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
