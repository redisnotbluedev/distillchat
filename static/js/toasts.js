(() => {
	const toastContainer = document.getElementById("toasts");

	window.showToast = (level, message) => {
		const toast = document.createElement("li");
		toast.className = level;
		toast.innerHTML = `
			<svg width="1em" height="1em"><use href="#icon-${{ "info": "info", "success": "circle-check", "warn": "triangle-alert", "warning": "triangle-alert", "error": "circle-x" }[level]
			}"></use></svg>
			<span>${message}</span>
			<button><svg width="1em" height="1em"><use href="#icon-x"></use></svg></button>
		`;
		function removeToast() {
			toast.classList.toggle("removed", true);
			toast.addEventListener("animationend", () => {
				if (toast.parentNode) toast.remove();
			})
		}

		toast.querySelector("button").addEventListener("click", removeToast);
		setTimeout(removeToast, 5000)
		toastContainer.appendChild(toast);
	}
})()
