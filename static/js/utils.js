/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { showToast } from "./toasts.js";

export function icon(name) {
	return `<svg viewBox="0 0 24 24"><use href="#icon-${name}"></use></svg>`;
}

export function copy(button, text) {
	navigator.clipboard
		.writeText(text)
		.then(() => {
			button.innerHTML = icon("check");
			setTimeout(() => {
				button.innerHTML = icon("copy");
			}, 2000);
		})
		.catch((error) => {
			showToast("error", `Failed to copy: ${error}`);
		});
}

export function formatBytes(bytes, dp = 0) {
	if (!bytes) return "0 B";
	const i = Math.floor(Math.log(bytes) / Math.log(1024));
	return (
		(bytes / Math.pow(1024, i)).toFixed(dp) +
		" " +
		["B", "KB", "MB", "GB", "TB"][i]
	);
}
export function getRelativeTime(date) {
	const now = new Date();
	const diffInSeconds = Math.round((date - now) / 1000);
	const diffInDays = Math.round(diffInSeconds / 86400);

	if (diffInDays === -1) {
		return "yesterday";
	}

	if (diffInDays <= -7 && diffInDays > -14) {
		return "last week";
	}

	if (diffInDays <= -30 && diffInDays > -60) {
		return "last month";
	}

	if (diffInDays <= -365 && diffInDays > -730) {
		return "last year";
	}

	const units = [
		{ name: "year", seconds: 31536000 },
		{ name: "month", seconds: 2592000 },
		{ name: "week", seconds: 604800 },
		{ name: "day", seconds: 86400 },
		{ name: "hour", seconds: 3600 },
		{ name: "minute", seconds: 60 },
		{ name: "second", seconds: 1 },
	];

	const rtf = new Intl.RelativeTimeFormat(navigator.language, { numeric: "auto" });

	for (const unit of units) {
		if (Math.abs(diffInSeconds) >= unit.seconds || unit.name === "second") {
			const value = Math.round(diffInSeconds / unit.seconds);
			return rtf.format(value, unit.name);
		}
	}
}
