// Runs the Space's own start-up (boot.js) on the self-hosted Pyodide files, then the scripted sessions of
// parity_driver.py, and compares the result with the CPython reference byte for byte.
// FOOL_PARITY_SPEED=1 also times a +2 h click and the sliced rebuild of a whole 24 h session (about a minute more).
// Usage: node --disallow-code-generation-from-strings pyodide_parity.mjs EXPECTED_JSON
// (the flag makes eval / new Function fail, as the page's Content-Security-Policy does without 'unsafe-eval')
import { loadPyodide } from "pyodide";   // the pinned npm package: the same loader the page ships
import crypto from "node:crypto";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { boot } from "../boot.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const space = path.resolve(here, "..");
const demo = path.resolve(space, "../../examples/simulators/scenarios/demo.json");
const expectedPath = process.argv[2];
if (!expectedPath) throw new Error("usage: pyodide_parity.mjs EXPECTED_JSON");

const sha = (file) => crypto.createHash("sha256").update(fs.readFileSync(file)).digest("hex");
const lap = (label, since) => console.log(`  ${label}: ${((performance.now() - since) / 1000).toFixed(2)} s`);

// The npm package and the Space's pyodide/ folder must be the same Pyodide build.
for (const name of ["pyodide.asm.wasm", "pyodide.asm.mjs", "pyodide.mjs", "python_stdlib.zip", "pyodide-lock.json"]) {
  const npmFile = path.join(here, "node_modules", "pyodide", name);
  if (sha(npmFile) !== sha(path.join(space, "pyodide", name))) throw new Error(`${name}: the Space's copy differs from the npm package`);
}
console.log("Space pyodide/ files are byte-identical to the pinned npm package");

const stages = [];
let t = performance.now();
const py = await boot({
  loadPyodide,
  indexURL: path.join(space, "pyodide") + path.sep,
  readBytes: async (file) => new Uint8Array(fs.readFileSync(path.join(space, file))),
  progress: (fraction, text) => stages.push(`${Math.round(fraction * 100)}% ${text}`),
});
lap("boot (Pyodide, packages, wheels, pomona.zip, engine_api)", t);
console.log("  progress messages:", stages.join(" | "));
console.log("  Python", py.version, py.runPython("import sys; sys.version.split()[0]"));

py.FS.mkdirTree("/check");
py.FS.writeFile("/check/parity_driver.py", fs.readFileSync(path.join(here, "parity_driver.py")));
py.FS.writeFile("/check/demo.json", fs.readFileSync(demo));
t = performance.now();
const got = JSON.parse(py.runPython(`
import sys
sys.path.insert(0, "/check")
import parity_driver
parity_driver.run_all("/app", "/check/demo.json", sync=True, speed=${process.env.FOOL_PARITY_SPEED ? "True" : "False"})
`));
lap("scripted sessions (a, b, c, d)" + (process.env.FOOL_PARITY_SPEED ? " and speed runs" : ""), t);

const expected = JSON.parse(fs.readFileSync(expectedPath, "utf8"));
const names = Object.keys(JSON.parse(expected.results_json));
const gotResults = JSON.parse(got.results_json), wantResults = JSON.parse(expected.results_json);
let allSame = got.results_json === expected.results_json;
for (const name of names) {
  const same = JSON.stringify(gotResults[name]) === JSON.stringify(wantResults[name]);
  allSame = allSame && same;
  console.log(`  ${name}: ${same ? "IDENTICAL" : "DIFFERENT"} (${JSON.stringify(gotResults[name]).length} bytes)`);
}
console.log("  CPython", expected.python.split(" ")[0], "vs Pyodide", got.python.split(" ")[0]);
console.log("  timings (s):", JSON.stringify(Object.fromEntries(Object.entries(got.timings).map(([k, v]) => [k, Math.round(v * 100) / 100]))));
if (!allSame) {
  console.error("Pyodide and CPython results differ");
  process.exit(1);
}
console.log(`PARITY OK: ${names.length} scenarios byte-identical (${got.results_json.length} bytes of results)`);
