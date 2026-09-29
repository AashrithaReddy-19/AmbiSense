// The test suite reads stylesheet source through Node's fs; declared here so the project type-checks without installing @types/node.
declare module "node:fs" {
  export function readFileSync(path: string | URL, encoding: "utf8"): string;
}
