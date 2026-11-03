// Starts Pomona's Python: Pyodide, the packages the engine imports, two pure-Python wheels and pomona.zip.
// Shared by worker.js (the browser) and tests/pyodide_parity.mjs (Node), so the check runs the page's own start-up.
// Everything is read from the Space itself (pyodide/, wheels/, pomona.zip); nothing comes from a CDN or PyPI.

// Packages from Pyodide's own lock file (pydantic and httpx with their dependencies).
export const PACKAGES = ["pydantic", "pydantic_core", "typing-extensions", "annotated-types", "typing-inspection",
  "httpx", "httpcore", "h11", "anyio", "sniffio", "certifi", "idna"];
// Pure-Python wheels Pyodide does not ship; unpacked straight into site-packages (no micropip, no PyPI at runtime).
export const WHEELS = ["python_dotenv-1.2.4-py3-none-any.whl", "pydantic_settings-2.11.0-py3-none-any.whl"];

/**
 * @param loadPyodide  loadPyodide from pyodide.mjs
 * @param indexURL     where pyodide.asm.wasm, python_stdlib.zip, pyodide-lock.json and the package wheels are
 * @param readBytes    async (path relative to the Space root) => Uint8Array
 * @param progress     (fraction 0..1, text) => void
 */
export async function boot({ loadPyodide, indexURL, readBytes, progress = () => {} }) {
  progress(0.03, "Starting Python");
  const py = await loadPyodide({ indexURL });
  progress(0.5, "Loading the Python packages");
  await py.loadPackage(PACKAGES);
  progress(0.85, "Unpacking Pomona's code");
  for (const wheel of WHEELS) py.unpackArchive(await readBytes(`wheels/${wheel}`), "wheel");
  py.FS.mkdirTree("/app");
  py.unpackArchive(await readBytes("pomona.zip"), "zip", { extractDir: "/app" });
  progress(0.95, "Starting the engine");
  py.runPython(`
import sys
sys.path.insert(0, "/app")
import engine_api
engine_api.install_sync_loop()
`);
  progress(1, "Ready");
  return py;
}
