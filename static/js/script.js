import { state } from "./state.js";
import "./attachments.js"
import "./model.js"
import "./chat.js"
import { initMessages } from "./messages.js";

const messageContainer = document.getElementById("messages");
state.currentLeaf = messageContainer?.lastElementChild;
state.currentModel = localStorage.getItem("model") || document.querySelector("#modelMenu button.selected").dataset.id;

if (!isNewChat) {
	initMessages();
}
