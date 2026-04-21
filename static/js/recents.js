/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import "./chat.js";
import { getRelativeTime, icon } from "./utils.js";

const chatList = document.getElementById("chat-list");
const searchInput = document.getElementById("search");
const status = document.getElementById("status");
const loadingIndicator = document.getElementById("loading");

let limit = 20;
let offset = chatList.querySelectorAll("li").length;
let query = "";
let loading = false;
let hasMore = offset < initialTotalCount;

chatList.querySelectorAll("time").forEach(time => {
	const date = new Date(time.dateTime);
	time.innerText = getRelativeTime(date);
	time.dataset.tooltip = date.toLocaleString(undefined, {
		month: "long",
		day: "numeric",
		year: "numeric",
		hour: "numeric",
		minute: "numeric",
		hour12: true
	});
});

function renderChatItem(chat) {
	const li = document.createElement("li");
	li.innerHTML = `
		<a href="/chat/${chat.id}">
			<h4 class="chat-name">${chat.title}</h4>
			<p>Last message <time datetime="${chat.updated_at}"></time></p>
		</a>
		<button aria-haspopup="menu" popovertarget="chat-${chat.id}">${icon("ellipsis")}</button>
		<menu role="menu" id="chat-${chat.id}" popover>
			<li role="none">
				<button role="menuitem" class="rename">
					${icon("pencil")}
					Rename
				</button>
			</li>
			<li role="none">
				<button role="menuitem" class="delete">
					${icon("trash")}
					Delete
				</button>
			</li>
		</menu>
	`;
	updateTime(li.querySelector("time"));
	return li;
}

async function fetchChats(reset = false) {
	if (loading) return;
	if (!reset && !hasMore) return;

	loading = true;
	loadingIndicator.style.display = "flex";

	if (reset) {
		offset = 0;
		chatList.innerHTML = "";
	}

	const url = `/api/chats?limit=${limit}&offset=${offset}${query ? `&query=${encodeURIComponent(query)}` : ""}`;
	try {
		const res = await fetch(url);
		if (!res.ok) throw new Error("Failed to fetch chats");
		const data = await res.json();

		data.chats.forEach(chat => {
			chatList.appendChild(renderChatItem(chat));
		});

		offset += data.chats.length;
		hasMore = offset < data.total_count;

		status.textContent = query === ""
			? `${data.total_count} chat${data.total_count === 1 ? "" : "s"} with ${AI_NAME}`
			: `${data.total_count} chat${data.total_count === 1 ? "" : "s"} matching "${query}"`;
	} catch (e) {
		console.error(e);
	} finally {
		loading = false;
		loadingIndicator.style.display = "none";
	}
}

let debounceTimeout;
searchInput.addEventListener("input", e => {
	clearTimeout(debounceTimeout);
	debounceTimeout = setTimeout(() => {
		query = e.target.value;
		fetchChats(true);
	}, 300);
});

chatList.addEventListener("scroll", () => {
	const { scrollTop, scrollHeight, clientHeight } = chatList;
	// If scrolled to within 100px of the bottom
	if (scrollTop + clientHeight >= scrollHeight - 100) {
		if (hasMore && !loading) {
			fetchChats();
		}
	}
});

// Check if we need to load more immediately (e.g. if the initial list is too short)
if (hasMore && chatList.scrollHeight <= chatList.clientHeight) {
	fetchChats();
}
