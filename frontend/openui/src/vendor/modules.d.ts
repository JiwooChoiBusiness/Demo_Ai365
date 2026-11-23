// 형 정의가 없는 react-syntax-highlighter 경로들(빌드 별칭에서만 쓴다).
// Type stubs for react-syntax-highlighter paths that ship no types (used only by the build aliases).
declare module "react-syntax-highlighter/dist/esm/prism-light.js" {
  const PrismLight: unknown;
  export default PrismLight;
}

declare module "react-syntax-highlighter/dist/esm/languages/prism/*" {
  const language: unknown;
  export default language;
}

declare module "react-syntax-highlighter/dist/esm/styles/prism/one-light.js" {
  const style: Record<string, Record<string, string>>;
  export default style;
}
