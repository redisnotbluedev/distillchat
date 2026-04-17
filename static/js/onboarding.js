/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/
import "./chat.js";
import { showToast } from "./toasts.js";

const container = document.getElementById("form");

container.scrollTo(0, 0);
window.goToStep = async n => {
	if (n == 2 && !document.querySelector("input[name=name]").value) return;
	container.scrollTo({ left: n * container.offsetWidth, behavior: "smooth" })
}
container.addEventListener("submit", e => {
	e.preventDefault();
	fetch("/onboarding", { method: "POST", body: new FormData(e.target) })
		.then(r => { if (!r.ok) { throw new Error(`HTTP error ${r.status}`) } else { goToStep(3); }})
		.catch(err => {
			showToast("error", `Failed to complete onboarding: ${err.message}`)
		});
});
