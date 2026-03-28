import "./chat.js";
import { getRelativeTime } from "./utils.js";

document.getElementById("search").addEventListener("input", e => {
	const query = e.target.value;
	let results = 0;
	document.querySelectorAll(".recents > ul > li").forEach(c => {
		const found = c.querySelector("a > h4").textContent.toLowerCase().includes(query.toLowerCase());
		c.hidden = !found;
		if (found) { results += 1; }
	});
	document.getElementById("status").textContent = query === "" ? `${results} chats with Claude` : `${results} chat${results === 1 ? "" : "s"} matching "${query}"`;
});

document.querySelectorAll(".recents > ul > li > a > p > time").forEach(time => {
	const date = new Date(time.dateTime);

	time.innerText = getRelativeTime(date)
	time.dataset.tooltip = date.toLocaleString(undefined, {
		month: "long",
		day: "numeric",
		year: "numeric",
		hour: "numeric",
		minute: "numeric",
		hour12: true
	});
});
