// react-syntax-highlighter/dist/cjs/styles/prism/index.js 대신(vite.config.ts 의 별칭). 원본은 모든 테마를 한꺼번에
// 담는다. 데모는 밝은 테마만 쓰므로 one-light 하나를 두 이름으로 낸다.
// Stands in for react-syntax-highlighter/dist/cjs/styles/prism/index.js (an alias in vite.config.ts). The original
// holds every theme at once; the demo is light only, so one-light is exported under both names.
import oneLight from "react-syntax-highlighter/dist/esm/styles/prism/one-light.js";

export { oneLight, oneLight as vscDarkPlus };
