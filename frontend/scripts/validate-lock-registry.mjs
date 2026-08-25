import { readFile } from "node:fs/promises";

const ALLOWED_REGISTRIES = new Set(["registry.npmjs.org"]);
const lock = JSON.parse(
  await readFile(new URL("../package-lock.json", import.meta.url), "utf8"),
);
const invalid = [];

for (const [name, metadata] of Object.entries(lock.packages ?? {})) {
  if (!metadata?.resolved) continue;
  try {
    const resolved = new URL(metadata.resolved);
    if (resolved.protocol !== "https:" || !ALLOWED_REGISTRIES.has(resolved.hostname)) {
      invalid.push(`${name || "<root>"}: ${resolved.origin}`);
    }
  } catch {
    invalid.push(`${name || "<root>"}: invalid resolved URL`);
  }
}

if (invalid.length) {
  console.error("package-lock.json contains unapproved dependency registries:");
  for (const finding of invalid.slice(0, 20)) console.error(`- ${finding}`);
  process.exitCode = 1;
} else {
  console.log("package-lock.json dependency registries are approved");
}
