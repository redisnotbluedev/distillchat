import { showToast } from "./toasts.js";
import { getRelativeTime, icon } from "./utils.js";
import "./chat.js";
import "./attachments.js";

const editModal = document.getElementById("project-details-modal");
const deleteModal = document.getElementById("project-delete-modal");

document.querySelector(".project .project-edit").addEventListener("click", e => {
	editModal.querySelector("form").dataset.id = project;
	editModal.querySelector("input[type=text]").value = document.querySelector(".project > div > div > h1").innerText;
	editModal.querySelector("textarea").value = document.querySelector(".project > div > div > p").innerText;
	editModal.showModal();
});
document.querySelector(".project .project-delete").addEventListener("click", e => {
	deleteModal.querySelector("form").dataset.id = project;
	deleteModal.showModal();
})

document.querySelector("#pin, #unpin").addEventListener("click", event => {
	const button = event.target.closest("button");
	const pin = button.id === "pin";
	fetch(`/api/project/${project}/pinned`, {
		method: "POST",
		headers: { "Content-Type": "application/json" },
		body: JSON.stringify({ pinned: pin })
	}).then(response => {
		if (response.ok) {
			button.id = pin ? "unpin" : "pin";
			button.innerHTML = pin ? icon("pin-off") : icon("pin");
			if (pin) {
				const entry = document.createElement("li");
				entry.innerHTML = `
					${ icon("folder") }
					<a href="${ location.pathname }" class="chat-name">${ document.querySelector(".project > div > div > h1").innerText }</a>
					<button aria-haspopup="menu" popovertarget="sidebar-pinned-project">${ icon("ellipsis") }</button>
					<menu role="menu" id="sidebar-pinned-project" popover>
						<li role="none">
							<button role="menuitem" class="project-unpin">
								${ icon("pin-off") }
								Unpin
							</button>
						</li>
						<li role="none">
							<button role="menuitem" class="project-edit">
								${ icon("pencil") }
								Edit details
							</button>
						</li>
						<li role="none">
							<button role="menuitem" class="project-delete">
								${ icon("trash") }
								Delete
							</button>
						</li>
					</menu>
				</li>`
				document.getElementById("pinned").prepend(entry);
			} else {
				document.querySelector(`#pinned > li:has(> a[href^="${location.pathname}"])`).remove();
			}
		} else {
			showToast("error", `Failed to pin project: Error ${response.status}`);
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
