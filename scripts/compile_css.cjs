const fs = require('fs');
const path = require('path');
const vm = require('vm');

const htmlPath = path.join(__dirname, '../static/index.html');
const appJsPath = path.join(__dirname, '../static/js/app.js');
const tailwindJsPath = path.join(__dirname, 'vendor/tailwind.js');
const outCssPath = path.join(__dirname, '../static/css/tailwind.min.css');

const html = fs.readFileSync(htmlPath, 'utf8');
const appJs = fs.readFileSync(appJsPath, 'utf8');
const tailwindJs = fs.readFileSync(tailwindJsPath, 'utf8');

// 收集所有 class
const classes = new Set();

// 1. 从 HTML 中匹配 class="..." 和 :class="..."
const classAttrRegex = /:?class="([^"]+)"/g;
let match;
while ((match = classAttrRegex.exec(html)) !== null) {
  const content = match[1];
  // 匹配字符串字面量或直接 class
  const tokens = content.match(/[\w\-/:.[\]#%]+|'[^']+'/g) || [];
  for (let token of tokens) {
    token = token.replace(/^'|'$/g, '').trim();
    if (token && !token.includes('{') && !token.includes('}') && !token.includes('?') && !token.includes(':') || /^[a-zA-Z0-9_\-\/\[\]#.:%]+$/.test(token)) {
      classes.add(token);
    }
  }
}

// 2. 从 HTML 源码全文中匹配明显的 tailwind class 模式
const allHtmlWords = html.match(/[a-zA-Z0-9_\-\/\[\]#.:%]+/g) || [];
for (const w of allHtmlWords) {
  if (w.includes('-') || w.includes('[') || w.includes(':') || w === 'flex' || w === 'block' || w === 'inline' || w === 'hidden' || w === 'absolute' || w === 'relative' || w === 'fixed' || w === 'sticky') {
    classes.add(w);
  }
}

// 3. 从 JS 源码中匹配引号内的 class
const jsWords = appJs.match(/'([^'\n]+)'|"([^"\n]+)"/g) || [];
for (let j of jsWords) {
  j = j.slice(1, -1).trim();
  const parts = j.split(/\s+/);
  for (const part of parts) {
    if (part.includes('-') || part.includes(':') || part === 'flex' || part === 'hidden' || part === 'block' || part === 'truncate') {
      classes.add(part);
    }
  }
}

// 4. 手动补全动态拼接的常见颜色与状态类
const dynamicVariants = [
  'bg-emerald-500', 'animate-pulse', 'bg-amber-400', 'bg-rose-500', 'bg-cyan-500',
  'border-emerald-500/40', 'text-emerald-300', 'text-emerald-400', 'text-emerald-500',
  'border-rose-500/40', 'text-rose-300', 'text-rose-400',
  'border-cyan-500/40', 'text-cyan-300', 'text-cyan-400',
  'border-amber-500/40', 'text-amber-300', 'text-amber-400',
  'border-[#232D3B]', 'bg-[#12171F]', 'bg-[#0A0D12]', 'bg-[#161D27]', 'bg-[#1C2432]',
  'border-emerald-500/50', 'border-rose-500/50',
  'text-gray-200', 'text-gray-300', 'text-gray-400', 'text-gray-500', 'text-gray-600',
  'ph-check-circle', 'ph-x-circle', 'ph-info', 'ph-warning',
  'hover:bg-[#161D27]', 'hover:bg-[#1C2432]', 'hover:text-emerald-400', 'hover:border-emerald-500/40',
  'group-hover:text-emerald-400', 'group-hover:text-amber-400',
  'dark:bg-dark-bg', 'dark:bg-dark-panel', 'dark:bg-dark-card', 'dark:border-dark-border', 'dark:hover:bg-dark-hover'
];
dynamicVariants.forEach(c => classes.add(c));

console.log(`Compiled candidate class pool: ${classes.size} classes`);

const styleElement = {
  isConnected: true,
  textContent: "",
  getAttribute: () => null,
};

const headElement = {
  append: () => { styleElement.isConnected = true; }
};

const bodyElement = {
  classList: new Set(),
};

const docElement = {
  classList: new Set(["dark"]),
};

const observer = class {
  observe() {}
  disconnect() {}
};

const windowObj = {
  MutationObserver: observer,
  addEventListener: () => {},
  removeEventListener: () => {},
};

// 分批塞到多个虚拟元素上，避免单个 classList 过大
const classListArray = Array.from(classes);
const chunkSize = 50;
const virtualElements = [];
for (let i = 0; i < classListArray.length; i += chunkSize) {
  virtualElements.push({
    classList: classListArray.slice(i, i + chunkSize)
  });
}

const documentObj = {
  documentElement: docElement,
  head: headElement,
  body: bodyElement,
  createElement: (tag) => {
    if (tag === "style") return styleElement;
    return {};
  },
  querySelectorAll: (selector) => {
    if (selector.includes("style")) return [];
    if (selector === "[class]") {
      return virtualElements;
    }
    return [];
  },
  addEventListener: () => {},
};

windowObj.window = windowObj;
windowObj.document = documentObj;

const context = vm.createContext({
  window: windowObj,
  document: documentObj,
  MutationObserver: observer,
  console: { log() {}, warn() {}, error: console.error },
  setTimeout: setTimeout,
  clearTimeout: clearTimeout,
  self: windowObj,
  process: process,
  Buffer: Buffer,
});

vm.runInContext(tailwindJs, context);
context.window.tailwind.config = {
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        dark: {
          bg: '#0A0D12',
          panel: '#12171F',
          card: '#161D27',
          border: '#232D3B',
          hover: '#1C2432'
        }
      }
    }
  }
};

setTimeout(() => {
  const css = styleElement.textContent;
  if (!css || css.length < 500) {
    console.error("Failed to generate CSS! Length:", css.length);
    process.exit(1);
  }
  fs.writeFileSync(outCssPath, css, 'utf8');
  console.log(`Successfully generated static CSS: ${outCssPath} (${(css.length / 1024).toFixed(1)} KB)`);
  process.exit(0);
}, 1200);
