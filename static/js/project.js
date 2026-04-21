import { showToast } from "./toasts.js";
import { getRelativeTime } from "./utils.js";
import "./chat.js";

const editModal = document.getElementById("project-details-modal");
const deleteModal = document.getElementById("project-delete-modal");

document.querySelector(".project-edit").addEventListener("click", e => {
	editModal.querySelector("input[type=text]").value = document.querySelector(".project > div > div > h1").innerText;
	editModal.querySelector("textarea").value = document.querySelector(".project > div > div > p").innerText;
	editModal.showModal();
});
document.querySelector(".project-delete").addEventListener("click", e => { deleteModal.showModal() })

editModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	editModal.close();
	const data = Object.fromEntries((new FormData(event.target)).entries());

	fetch(`/api/project/${project}`, {
		method: "PATCH",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify(data)
	}).then(response => {
		if (response.ok) {
			document.querySelector(".project > div > div > h1").innerText = data.name;
			document.querySelector(".project > div > div > p").innerText = data.description;
		} else {
			showToast("error", `Failed to edit details: Error ${response.status}`);
		}
	});
});

deleteModal.querySelector("form").addEventListener("submit", event => {
	event.preventDefault();
	deleteModal.close();

	fetch(`/api/project/${project}`, {
		method: "DELETE"
	}).then(response => {
		if (response.ok) {
			location.href = "/projects";
		} else {
			showToast("error", `Failed to delete project: Error ${response.status}`);
		}
	});
});

document.querySelectorAll(".project ul time").forEach(time => {
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
