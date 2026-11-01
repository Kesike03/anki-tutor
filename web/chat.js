"use strict";

const parser = window.markdownit({ html: false, linkify: false, breaks: true });
parser.renderer.rules.image = (tokens, index) =>
    `[Image: ${parser.utils.escapeHtml(tokens[index].content)}]`;
parser.renderer.rules.link_open = () => "";
parser.renderer.rules.link_close = () => "";

let latestRender = 0;
let renderQueue = Promise.resolve();

document.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-action]");
    if (button && !button.disabled) {
        pycmd(`tutor:${button.dataset.action}:${button.dataset.id}`);
    }
});

function tool(action, id, symbol, title, disabled = false) {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.action = action;
    button.dataset.id = String(id);
    button.textContent = symbol;
    button.title = title;
    button.setAttribute("aria-label", title);
    button.disabled = disabled;
    return button;
}

function markdownWithMath(source) {
    const expressions = [];
    const protectedText = source.replace(
        /\\\([\s\S]*?\\\)|\\\[[\s\S]*?\\\]|\$\$[\s\S]+?\$\$|(?<!\\)\$(?!\s)(?:\\.|[^$\\])+?\$/g,
        (expression) => {
            const index = expressions.push(expression) - 1;
            return `\uE000${index}\uE001`;
        },
    );
    return parser.render(protectedText).replace(/\uE000(\d+)\uE001/g, (_match, index) =>
        parser.utils.escapeHtml(expressions[Number(index)]),
    );
}

window.renderTutorMessages = function (payload) {
    const version = ++latestRender;
    renderQueue = renderQueue.catch(() => {}).then(async () => {
        if (version !== latestRender) return;
        const root = document.getElementById("thread");
        if (window.MathJax?.typesetClear) window.MathJax.typesetClear([root]);
        root.replaceChildren();
        for (const message of payload.messages) {
            const entry = document.createElement("section");
            entry.className = `message ${message.role === "user" ? "user" : "assistant"}`;
            const label = document.createElement("div");
            label.className = "role";
            label.textContent = message.role === "user" ? payload.you : payload.tutor;
            const body = document.createElement("div");
            body.className = "body";
            body.innerHTML = markdownWithMath(message.content);
            entry.append(label, body);
            if (message.attachments?.length) {
                const files = document.createElement("div");
                files.className = "files";
                files.textContent = message.attachments.map((file) => file.name).join(" · ");
                entry.append(files);
            }
            if (message.id) {
                const controls = document.createElement("div");
                controls.className = "controls";
                if (message.role === "assistant") {
                    controls.append(
                        tool("copy", message.id, "⧉", payload.labels.copy),
                        tool("regen", message.id, "↻", payload.labels.regenerate, payload.busy),
                    );
                } else {
                    controls.append(tool("edit", message.id, "✎", payload.labels.edit_message, payload.busy));
                }
                if (message.branch_total > 1) {
                    controls.append(
                        tool("prev", message.id, "‹", payload.labels.previous_branch,
                            payload.busy || message.branch_index === 1),
                    );
                    const count = document.createElement("span");
                    count.className = "branch-count";
                    count.textContent = `${message.branch_index}/${message.branch_total}`;
                    controls.append(count);
                    controls.append(
                        tool("next", message.id, "›", payload.labels.next_branch,
                            payload.busy || message.branch_index === message.branch_total),
                    );
                }
                entry.append(controls);
            }
            root.append(entry);
        }
        for (const [name, value] of Object.entries(payload.theme)) {
            document.documentElement.style.setProperty(`--${name}`, value);
        }
        await window.MathJax.startup.promise;
        if (version !== latestRender) return;
        await window.MathJax.typesetPromise([root]);
        window.scrollTo(0, document.body.scrollHeight);
    }).catch((error) => console.error("Tutor rendering failed", error));
};
