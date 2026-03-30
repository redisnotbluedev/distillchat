/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { showToast } from "./toasts.js";

const form = document.getElementById("settings");
const saver = document.getElementById("confirm");
const capture = _ => { initialState = new URLSearchParams(new FormData(form)).toString() };
let initialState = "";

if (document.readyState === "loading") {
	window.addEventListener("DOMContentLoaded", capture);
} else {
	capture();
}

form.addEventListener("input", (_) => {
	const currentState = new URLSearchParams(new FormData(form)).toString();
	saver.hidden = currentState === initialState;
});

form.addEventListener("submit", (e) => {
	e.preventDefault();
	const data = Object.fromEntries(new FormData(form).entries());
	fetch("/api/settings", {
		method: "PATCH",
		headers: {
			"Content-Type": "application/json",
		},
		body: JSON.stringify(data),
	}).then((response) => {
		if (!response.ok) {
			showToast("error", "Failed to save settings");
		} else {
			window.location.reload();
		}
	});
});
