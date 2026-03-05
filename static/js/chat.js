(function () {
	const chatInput = document.getElementById("chatInput");
	const sendButton = document.getElementById("sendButton");
	const messageContainer = document.getElementById("messages");
	const messageScroll = messageContainer?.parentElement;

	function icon(name) {
		return `<svg width="1em" height="1em"><use href="#icon-${ name }"></use></svg>`
	}

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
				location.href = `/chat/${ data.id }`;
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
			userMessage.innerHTML = marked.parse(message);
			messageContainer.appendChild(userMessage);

			const assistantMessage = document.createElement("div");
			assistantMessage.className = "message assistant";
			messageContainer.appendChild(assistantMessage);

			messageScroll.scrollTo({
				top: messageScroll.scrollHeight,
				behavior: "smooth"
			})

			fetch(`/api/chats/${ chatID }/send_message`, {
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
		let text = ""

		while (true) {
			const { value, done } = await reader.read();
			if (done) break;

			const chunk = decoder.decode(value, { stream: true });
			const lines = (buffer + chunk).split("\n");
			const scrollTolerance = 1;
			buffer = lines.pop();

			for (const line of lines) {
				if (line.trim().startsWith("data: ")) {
					const data = JSON.parse(line.trim().slice(6));
					switch (data.type) {
						case "TokenEvent":
							text += data.content;
							messageElement.innerHTML = marked.parse(text);

							const scrollNeeded = messageScroll.scrollHeight - messageScroll.clientHeight - messageScroll.scrollTop;
							if (scrollNeeded > scrollTolerance) {
								messageScroll.scrollTo({
									top: messageScroll.scrollHeight,
									behavior: scrollNeeded > 50 ? "smooth" : "instant"
								});
							}
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
		document.querySelector(`aside a[href="/chat/${ chatID }"]`).classList.toggle("selected", true)

		if (document.querySelector(".messages > .message.user:last-child")) {
			const message = document.createElement("div");
			message.className = "message assistant";
			messageContainer.appendChild(message);

			fetch(`/api/chats/${ chatID }/regenerate`, {
				method: "POST",
				headers: { "Content-Type": "application/json" }
			}).then(async response => {
				await streamResponse(message, response);
			}).catch(e => {
				console.error(e);
			});
		}

		window.copyCode = button => {
			const code = button.closest("figure.code").querySelector("code").textContent;
			navigator.clipboard.writeText(code).then(() => {
				button.innerHTML = icon("check");
				setTimeout(() => { button.innerHTML = icon("copy") }, 2000);
			}).catch(error => {
				console.error(error)
			})
		}

		const renderer = {
			code({ text, lang }) {
				const language = lang && hljs.getLanguage(lang) ? lang : "plaintext";
				const highlighted = hljs.highlight(text, { language: language, ignoreIllegals: true }).value;
				return `
				<figure class="code">
					<figcaption>
						<span>${ language }</span>
						<button title="Copy" onclick="copyCode(this)">
							${ icon("copy") }
						</button>
					</figcaption>
					<pre><code class="hljs language-${language}">${ highlighted }</code></pre>
				</figure>`;
			}
		}
		marked.use({ renderer })

		document.querySelectorAll(".message").forEach(message => {
			message.innerHTML = marked.parse(message.textContent).trim();
		});

		setTimeout(() => messageScroll.scrollTo({ top: messageScroll.scrollHeight }), 20); // Let it render or smth idek but this makes it work better
	}
})();
