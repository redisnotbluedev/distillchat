/*
SPDX-License-Identifier: AGPL-3.0-or-later
Copyright (C) 2026 redisnotblue <147359873+redisnotbluedev@users.noreply.github.com>
*/

import { state } from "./state.js";
import "./attachments.js"
import "./model.js"
import "./chat.js"
import { initMessages } from "./messages.js";

state.currentLeaf = document.querySelector("#messages > div:last-of-type");
state.currentModel = localStorage.getItem("model") || document.querySelector("#modelMenu button.selected").dataset.id;

if (!isNewChat) {
	initMessages();
}
