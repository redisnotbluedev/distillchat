import { state } from "./state.js";
import { icon } from "./utils.js";

const modelMenu = document.getElementById("modelMenu");
const modelPicker = document.getElementById("modelPicker");

modelMenu.querySelectorAll("button").forEach(button => {
	button.addEventListener("click", e => {
		modelMenu.hidePopover();
		state.currentModel = button.dataset.id;
		localStorage.setItem("model", state.currentModel);
		modelMenu.querySelectorAll("button.selected").forEach(b => { b.classList.toggle("selected", false) })
		button.classList.toggle("selected", true);
		modelPicker.innerHTML = `${button.querySelector("h3").innerText} ${icon("chevron-down")}`;
	})
});

if (state.currentModel) {
	modelMenu.querySelectorAll("button.selected").forEach(b => { b.classList.toggle("selected", false) });
	const button = modelMenu.querySelector(`button[data-id="${state.currentModel}"]`);
	button.classList.toggle("selected", true);
	modelPicker.innerHTML = `${button.querySelector("h3").innerText} ${icon("chevron-down")}`;
}
