/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { state } from "./state.js";
import { icon, formatBytes } from "./utils.js";
import { showToast } from "./toasts.js";

const filePicker = document.getElementById("filePicker");
const attachmentContainer = document.getElementById("attachments");
const dragOverlay = document.getElementById("dragOverlay");
const chatInput = document.getElementById("chatInput");
const sendButton = document.getElementById("sendButton");
let _dragCounter = 0;

export function renderAttachment(file, attachmentKey) {
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
			delete state.uploads[attachmentKey];
			const shouldDisable = chatInput.textContent === "" && Object.keys(state.uploads).length === 0;
			chatInput.classList.toggle("empty", shouldDisable);
			sendButton.disabled = shouldDisable;
		}
		attachment.appendChild(remove);
	}

	return attachment;
}

export function handleFileUpload(files) {
	Array.from(files).forEach(f => {
		if (f.size > maxUploadSize) {
			showToast("warning", `You may not upload files larger than ${formatBytes(maxUploadSize)}.`);
			return;
		}
		const key = crypto.randomUUID();
		const attachment = renderAttachment(f, key);
		state.uploads[key] = f;
		attachmentContainer.appendChild(attachment);

		sendButton.disabled = false;
		chatInput.classList.toggle("empty", false);
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
