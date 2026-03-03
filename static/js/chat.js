(function () {
	const chatInput = document.getElementById("chatInput");
	const sendButton = document.getElementById("sendButton");
	const messageContainer = document.getElementById("messages");

	function onInputSubmit(event) {
		if (isNewChat) {
			fetch("/api/chats", {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ "message": chatInput.innerText })
			}).then(response => {
				if (response.ok) {
					return response.json();
				} else {
					throw new Error(response.status);
				}
			}).then(data => {
				location.href = `/chat/${data.id}`;
			}).catch(e => {
				console.log(e);
			});
		} else {
			const message = chatInput.innerText;
			chatInput.innerText = "";
			const event = new Event("input", {
				bubbles: true,
				cancelable: true
			});
			chatInput.dispatchEvent(event); // update the input box

			const userMessage = document.createElement("div");
			userMessage.className = "message user";
			userMessage.innerText = message;
			messageContainer.appendChild(userMessage);

			const assistantMessage = document.createElement("div");
			assistantMessage.className = "message assistant";
			messageContainer.appendChild(assistantMessage);

			fetch(`/api/chats/${chatID}/send_message`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ "message": message })
			}).then(async response => {
				await streamResponse(assistantMessage, response);
			}).catch(e => {
				console.error(e);
			});
		}
	}

	async function streamResponse(messageElement, response) {
		const reader = response.body.getReader();
		const decoder = new TextDecoder();
		let buffer = "";

		while (true) {
			const { value, done } = await reader.read();
			if (done) break;

			const chunk = decoder.decode(value, { stream: true });
			const lines = (buffer + chunk).split("\n");
			buffer = lines.pop();

			for (const line of lines) {
				if (line.trim().startsWith("data: ")) {
					const data = JSON.parse(line.trim().slice(6));
					switch (data.type) {
						case "TokenEvent":
							messageElement.innerHTML += data.content.replace(/\n/g, "<br>");
							break;
						case "DoneEvent":
							return;
					}
				}
			}
		}
	}

	chatInput.addEventListener("input", event => {
		sendButton.disabled = event.target.textContent === "";
		chatInput.classList.toggle("empty", event.target.textContent === "")
	});
	chatInput.addEventListener("keydown", event => {
		if (event.key === "Enter" && !event.shiftKey) {
			event.preventDefault();
			onInputSubmit();
		}
	});
	sendButton.addEventListener("click", onInputSubmit);

	if (!isNewChat) {
		document.querySelector(`aside a[href="/chat/${chatID}"]`).classList.toggle("selected", true)

		if (document.querySelector(".messages > .message.user:last-child")) {
			const message = document.createElement("div");
			message.className = "message assistant";
			messageContainer.appendChild(message);

			fetch(`/api/chats/${chatID}/regenerate`, {
				method: "POST",
				headers: { "Content-Type": "application/json" }
			}).then(async response => {
				await streamResponse(message, response);
			}).catch(e => {
				console.error(e);
			});
		}
	}
})();
