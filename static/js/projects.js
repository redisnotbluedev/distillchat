import { showToast } from "./toasts.js";
import { getRelativeTime } from "./utils.js";
import "./chat.js";

const editModal = document.getElementById("project-details-modal");
const deleteModal = document.getElementById("project-delete-modal");
let selectedProject = null;

document.addEventListener("click", event => {
	const editButton = event.target.closest("menu button.project-edit");
	if (editButton) {
		selectedProject = editButton.closest("li:has(> menu)");
		editModal.querySelector("input[type=text]").value = selectedProject.querySelector("a > h4").innerText;
		editModal.querySelector("textarea").value = selectedProject.querySelector("a > .description").innerText;
		editModal.showModal();
		return;
	}

	const deleteButton = event.target.closest("menu button.project-delete");
	if (deleteButton) {
		selectedProject = deleteButton.closest("li:has(> menu)");
		deleteModal.showModal();
		return;
	}
});

editModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	editModal.close();
	const data = Object.fromEntries((new FormData(event.target)).entries());
	const id = selectedProject.querySelector("a").href.split("/").pop();

	fetch(`/api/project/${id}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(data)
	}).then(response => {
		if (response.ok) {
			selectedProject.querySelector("a > h4").innerText = data.name;
			selectedProject.querySelector("a > .description").innerText = data.description;
		} else {
			showToast("error", `Failed to edit details: Error ${response.status}`);
		}
	});
});

deleteModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	deleteModal.close();
	const id = selectedProject.querySelector("a").href.split("/").pop();

	fetch(`/api/project/${id}`, {
		method: "DELETE"
	}).then(response => {
		if (response.ok) {
			selectedProject.remove();
		} else {
			showToast("error", `Failed to delete project: Error ${response.status}`);
		}
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
