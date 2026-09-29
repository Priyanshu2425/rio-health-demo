// Generate src/contracts.gen.ts from ../contracts/schema.json. Never edit the output by hand.
//   npm run gen:contracts          write
//   npm run gen:contracts -- --check  exit 1 if stale
import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { compile } from "json-schema-to-typescript";

const schema = JSON.parse(readFileSync(new URL("../../contracts/schema.json", import.meta.url)));
// Keep titles on the named models only; per-field titles make json2ts emit an alias per field.
function stripFieldTitles(node, isModel) {
  if (Array.isArray(node)) return node.forEach((n) => stripFieldTitles(n, false));
  if (!node || typeof node !== "object") return;
  if (!isModel) delete node.title;
  for (const [key, value] of Object.entries(node)) {
    if (key === "$defs") Object.values(value).forEach((d) => stripFieldTitles(d, true));
    else stripFieldTitles(value, false);
  }
}
stripFieldTitles(schema, true);

const out = new URL("../src/contracts.gen.ts", import.meta.url);

const ts = await compile(schema, "RioContracts", {
  unreachableDefinitions: true,
  additionalProperties: false,
  bannerComment:
    "/* Generated from contracts/schema.json by scripts/gen-contracts.mjs. Do not edit. */",
  style: { singleQuote: false },
});

if (process.argv.includes("--check")) {
  if (!existsSync(out) || readFileSync(out, "utf8") !== ts) {
    console.error("src/contracts.gen.ts is stale; run npm run gen:contracts");
    process.exit(1);
  }
  console.log("src/contracts.gen.ts is current");
} else {
  writeFileSync(out, ts);
  console.log("wrote src/contracts.gen.ts");
}
