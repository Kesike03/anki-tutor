"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const root = path.resolve(__dirname, "..");
const context = vm.createContext({ window: {}, console });
vm.runInContext(fs.readFileSync(path.join(root, "web/vendor/markdown-it.min.js"), "utf8"), context);
context.window.markdownit = context.markdownit;
vm.runInContext(fs.readFileSync(path.join(root, "web/chat.js"), "utf8"), context);

function render(source) {
    return vm.runInContext(`markdownWithMath(${JSON.stringify(source)})`, context);
}

const output = render("**Bold** and $x_i$ and \\(\\frac{1}{2}\\)");
assert.match(output, /<strong>Bold<\/strong>/);
assert.match(output, /\$x_i\$/);
assert.match(output, /\\\(\\frac\{1\}\{2\}\\\)/);
const unsafe = render("<script>alert(1)</script> ![pixel](https://example.com/a.png)");
assert.doesNotMatch(unsafe, /<script>|<img/);
console.log("Markdown and math rendering smoke test passed");
