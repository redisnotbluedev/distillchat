/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/
import { unzip } from "https://unpkg.com/unzipit@1.4.0/dist/unzipit.module.js";
import { showToast } from "./toasts.js";
import "./chat.js";

const container = document.getElementById("form");
const instructions = document.getElementById("steps");
const upload = document.getElementById("upload");
const importOptions = document.getElementById("import-options");
let chatBytes = 0;
const steps = {
	"anthropic": [
		`Go to <a href="https://claude.ai">Settings → Privacy</a>.`,
		`Select <b>Export Data</b>, then click <b>Export</b>.`,
		`Check your email and click <b>Download Data</b>.`
	],
	"openai": [
		`Go to <a href="https://chatgpt.com">Settings → Data controls</a>.`,
		`Select <b>Export</b>, then <b>Confirm export</b>.`,
		`Check your email and click <b>Download data export</b>.`
	],
	"google": [
		`Go to <a href="https://google.com">Google Takeout</a>.`,
		`Click <b>Deselect all</b>, then find and check <b>My Activity</b>.`,
		`Click <b>All activity data included</b>, deselect everything, then check <b>Gemini</b>, and click <b>OK</b>.`,
		`Click <b>Multiple formats</b> and set Activity records to <b>JSON</b>.`,
		`Scroll to the bottom, click <b>Next step</b>, then <b>Create export</b>.`,
		`Check your email, select <b>Manage Takeout request</b>, and click <b>Download</b>.`
	],
	"distillchat": [
		`Go to <b>Settings → Data controls</b>.`,
		`Click <b>Export data</b>.`
	]
};

container.scrollTo(0, 0);

window.goToStep = async n => {
	importOptions.classList.toggle("blocker", false);
	const mode = container.querySelector("input[type=radio][name=format]:checked").id;

	if (n === 1) {
		const data = steps[mode];
		instructions.innerHTML = "";
		data.forEach(s => { instructions.innerHTML += `<li>${s}</li>`; })
	}

	container.scrollTo({ left: n * container.offsetWidth, behavior: "smooth" });

	if (n === 3) {
		const file = upload.files[0];
		if (!file) {
			window.goToStep(2);
			return;
		}
		importOptions.classList.toggle("blocker", true);
		const { entries } = await unzip(file);
		importOptions.classList.toggle("blocker", false);
		let features = [];

		switch (mode) {
			case "anthropic":
				let userID = "";

				if ("users.json" in entries) {
					const users = JSON.parse(await entries["users.json"].text());
					if (users.length > 1) {
						showToast("error", "This is an organization export. Please export from an individual account.");
						window.goToStep(2);
						return;
					} else if (users.length == 1 && "full_name" in users[0]) {
						features.push("name");
						userID = users[0].uuid;
					}
				}

				if ("projects.json" in entries) {
					const projects = JSON.parse(await entries["projects.json"].text());
					if (projects.length >= 1) {
						features.push("projects");
					}
				}

				if ("memories.json" in entries) {
					const data = JSON.parse(await entries["memories.json"].text());
					if (data.length >= 1) {
						const memories = data.find(e => e["account_uuid"] === userID);
						if (memories["conversations_memory"]) features.push("memory");
					}
				}

				if ("conversations.json" in entries) {
					chatBytes = entries["conversations.json"].size;
					features.push("chats");
				}

				break;
			default:
				showToast("error", "Sorry, this platform is unsupported.");
				window.goToStep(0);
				return;
		}

		if (!features.length) {
			showToast("error", "We found no available data to import.");
			window.goToStep(2);
			return;
		}

		importOptions.innerHTML = "";
		features.forEach(e => {
			const l = e.replaceAll("_", " ");
			importOptions.innerHTML += `<label><input type="checkbox" name="include" value="${e}">${l.charAt(0).toUpperCase() + l.slice(1).toLowerCase()}</label>`;
		});
	}
}

container.addEventListener("submit", async e => {
	e.preventDefault();
	const raw = new FormData(container);
	const formData = new FormData();
	formData.append("format", raw.get("format"));
	raw.getAll("include").forEach(v => formData.append("include", v));
	formData.append("file", raw.get("file"));

	importOptions.parentElement.innerHTML = `<header><label for="progress" style="display:flex;align-items:center;gap:var(--size-sm);"><img style="height:1lh" src="/static/images/logo_loading.svg" alt="Loading"><span id="chats">Imported 0 chats</span></label></header><div><progress style="height:var(--size-lg);" id="progress" max="${chatBytes}"></progress></div><footer id="buttons"></footer>`;
	const chats = document.getElementById("chats");
	const progress = document.getElementById("progress");
	const buttons = document.getElementById("buttons");

	const resp = await fetch("/api/import", { method: "POST", body: formData });
	const reader = resp.body.getReader();
	const decoder = new TextDecoder();
	let buffer = "";

	while (true) {
		const { done, value } = await reader.read();
		if (done) break;
		buffer += decoder.decode(value, { stream: true });
		const lines = buffer.split("\n")
		buffer = buffer.endsWith("\n") ? "" : lines.pop()
		for (const line of lines) {
			if (!line.startsWith("data: ")) continue;
			const message = JSON.parse(line.slice(6));
			if (message.chats) chats.innerText = `Imported ${message.chats} chats`;
			if (message.read) progress.value = message.read;

			if (message.done) {
				break;
			}
		}
	}

	buttons.innerHTML = `<button onclick="location.href='/'">Home</button>`
	chats.innerText = "Done";
	progress.value = progress.max
});
