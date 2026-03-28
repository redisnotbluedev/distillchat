/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { showToast } from "./toasts.js";

export function icon(name) {
	return `<svg viewBox="0 0 24 24"><use href="#icon-${name}"></use></svg>`
}

export function copy(button, text) {
	navigator.clipboard.writeText(text).then(() => {
		button.innerHTML = icon("check");
		setTimeout(() => { button.innerHTML = icon("copy") }, 2000);
	}).catch(error => {
		showToast("error", `Failed to copy: ${error}`);
	});
}

export function formatBytes(bytes, dp = 0) {
	if (!bytes) return "0 B";
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	return (bytes / Math.pow(1024, i)).toFixed(dp) + " " + ["B", "KB", "MB", "GB", "TB"][i];
};
