// 섬 번들 진입점(static/openui/openui.js): 다시 내보내기만 하는 얇은 껍데기. 본체(window.AI365_OpenUI 를 세우는 곳)는
// src/api.tsx 이고, 빌드가 내용 해시 이름의 chunks/main-<해시>.js 로 묶는다. 화면은
// import('/static/openui/openui.js?v=<버전>') 으로 부른다.
// The island bundle's entry (static/openui/openui.js): a thin shell that only re-exports. The core (which sets
// window.AI365_OpenUI) is src/api.tsx, bundled as the content-hashed chunks/main-<hash>.js. The page loads it with
// import('/static/openui/openui.js?v=<version>').
export { default, render, unmount, toProgram, isProgram, wrapText, version } from "./api";
