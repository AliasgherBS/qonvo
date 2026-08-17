#!/usr/bin/env node
// Executable form of the pre-ship gates in
// docs/superpowers/specs/2026-08-17-frontend-overhaul-design.md section 10.
import { readFileSync, readdirSync, statSync, existsSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("..", import.meta.url));
const failures = [];
const fail = (gate, detail) => failures.push(`[${gate}] ${detail}`);

function walk(dir, out = []) {
  if (!existsSync(dir)) return out;
  for (const entry of readdirSync(dir)) {
    if (entry === "node_modules" || entry === ".next") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else out.push(full);
  }
  return out;
}

const SOURCE_DIRS = [join(ROOT, "app"), join(ROOT, "components"), join(ROOT, "lib")];
const sources = SOURCE_DIRS.flatMap((d) => walk(d)).filter((f) =>
  /\.(tsx?|css)$/.test(f),
);
const read = (f) => readFileSync(f, "utf8");
const rel = (f) => relative(ROOT, f);

// A line is exempt from a gate when it, or the line directly above it, carries
// `brand-ok: <gate>`. Exemptions are deliberate and reviewable in the diff,
// which is the point: a gate nobody can silence gets deleted, and a gate that
// cries wolf gets ignored.
const exempt = (lines, i, gate) => {
  const tag = `brand-ok: ${gate}`;
  return lines[i].includes(tag) || (i > 0 && lines[i - 1].includes(tag));
};

// Gate 1: brand tokens present and exact.
const BRAND = {
  "Signal Green": "#00C776",
  Ink: "#08130E",
  "Deep Forest": "#0B3B2B",
  Volt: "#C6FF3D",
  Paper: "#F3EFE6",
};
const globalsPath = join(ROOT, "app/globals.css");
const globals = existsSync(globalsPath) ? read(globalsPath) : "";
for (const [name, hex] of Object.entries(BRAND)) {
  if (!globals.toLowerCase().includes(hex.toLowerCase())) {
    fail("brand-tokens", `${name} ${hex} missing from app/globals.css`);
  }
}

// Gate 2: no em dash or en dash in any source file.
for (const f of sources) {
  const lines = read(f).split("\n");
  lines.forEach((line, i) => {
    if (exempt(lines, i, "no-dashes")) return;
    if (line.includes("—") || line.includes("–")) {
      fail("no-dashes", `${rel(f)}:${i + 1} contains an em or en dash`);
    }
  });
}

// Gate 3: no raw hex color outside globals.css.
for (const f of sources) {
  if (f.endsWith("globals.css")) continue;
  const lines = read(f).split("\n");
  lines.forEach((line, i) => {
    if (exempt(lines, i, "no-raw-hex")) return;
    if (/#[0-9a-fA-F]{6}\b/.test(line)) {
      fail("no-raw-hex", `${rel(f)}:${i + 1} hardcodes a hex color`);
    }
  });
}

// Gate 4: contact details only in lib/contact.ts.
const EMAIL = /[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}/;
const PHONE = /\+\d{7,}/;
for (const f of sources) {
  if (f.endsWith(join("lib", "contact.ts"))) continue;
  const lines = read(f).split("\n");
  lines.forEach((line, i) => {
    if (exempt(lines, i, "contact-isolation")) return;
    // A form placeholder is demonstrably not a reachable contact detail.
    if (line.includes("placeholder=")) return;
    if (EMAIL.test(line) || PHONE.test(line)) {
      fail("contact-isolation", `${rel(f)}:${i + 1} inlines a contact detail`);
    }
  });
}

// Gate 5: no price figures under app/.
for (const f of sources) {
  if (!f.startsWith(join(ROOT, "app"))) continue;
  const lines = read(f).split("\n");
  lines.forEach((line, i) => {
    if (exempt(lines, i, "no-prices")) return;
    if (/[$£€]\s?\d/.test(line)) {
      fail("no-prices", `${rel(f)}:${i + 1} contains a price figure`);
    }
  });
}

if (failures.length) {
  console.error(`verify-brand: ${failures.length} failure(s)\n`);
  for (const f of failures) console.error("  " + f);
  process.exit(1);
}
console.log("verify-brand: all gates passed");
