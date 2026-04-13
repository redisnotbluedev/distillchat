import { showToast } from "./toasts.js";

let form = document.querySelector("form#settings") || document.querySelector("form#delete");
const saver = document.getElementById("confirm");

if (form) {
	let method, endpoint;
	if (form.id === "settings") {
		method = "PATCH";
		endpoint = "/api/settings";
		form.addEventListener("input", (_) => {
			const currentState = new URLSearchParams(new FormData(form)).toString();
			if (saver) saver.hidden = currentState === initialState;
		});
	} else if (form.id === "delete") {
		method = "DELETE";
		endpoint = "/api/delete_account";
	}

	let initialState = "";
	const capture = _ => { initialState = new URLSearchParams(new FormData(form)).toString() };

	if (document.readyState === "loading") {
		window.addEventListener("DOMContentLoaded", capture);
	} else {
		capture();
	}

	form.addEventListener("submit", (e) => {
		e.preventDefault();
		const data = Object.fromEntries(new FormData(form).entries());
		fetch(endpoint, {
			method: method,
			headers: {
				"Content-Type": "application/json",
			},
			body: JSON.stringify(data),
		}).then(response => {
			if (!response.ok) {
				showToast("error", "Failed to save settings");
			} else {
				window.location.reload();
			}
		});
	});
}
