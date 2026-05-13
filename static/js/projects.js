import { getRelativeTime } from "./utils.js";
import "./chat.js";

const editModal = document.getElementById("project-details-modal");
const deleteModal = document.getElementById("project-delete-modal");

document.querySelectorAll(".projects menu button.project-edit").forEach(editButton => {
	editButton.addEventListener("click", () => {
		const selectedProject = editButton.closest("li:has(> menu)");
		editModal.querySelector("form").dataset.id = selectedProject.querySelector(`a[href^="/project"]`).href.split("/").pop();
		editModal.querySelector("input[type=text]").value = selectedProject.querySelector("a > h4").innerText;
		editModal.querySelector("textarea").value = selectedProject.querySelector("a > .description").innerText;
		editModal.showModal();
	});
});

document.querySelectorAll(".projects menu button.project-delete").forEach(deleteButton => {
	deleteButton.addEventListener("click", () => {
		deleteModal.querySelector("form").dataset.id = deleteButton.closest("li:has(> menu)").querySelector(`a[href^="/project"]`).href.split("/").pop();
		deleteModal.showModal();
	});
});

document.querySelectorAll(".projects ul time").forEach(time => {
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
