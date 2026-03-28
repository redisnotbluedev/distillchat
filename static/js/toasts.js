/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { icon } from "./utils.js";

const toastContainer = document.getElementById("toasts");

export function showToast(level, message) {
	const toast = document.createElement("li");
	toast.className = level;
	toast.innerHTML = `
		${icon({ "info": "info", "success": "circle-check", "warn": "triangle-alert", "warning": "triangle-alert", "error": "circle-x" }[level])}
		<span>${message}</span>
		<button>${icon("x")}</button>
	`;
	function removeToast() {
		toast.classList.toggle("removed", true);
		toast.addEventListener("animationend", () => {
			if (toast.parentNode) toast.remove();
		})
	}

	toast.querySelector("button").addEventListener("click", removeToast);
	setTimeout(removeToast, 5000)
	toastContainer.appendChild(toast);
}
