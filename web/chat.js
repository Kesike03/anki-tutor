"use strict";

const parser = window.markdownit({ html: false, linkify: false, breaks: true });
parser.renderer.rules.image = (tokens, index) =>
    `[Image: ${parser.utils.escapeHtml(tokens[index].content)}]`;
parser.renderer.rules.link_open = () => "";
parser.renderer.rules.link_close = () => "";

let latestRender = 0;
let renderQueue = Promise.resolve();

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
