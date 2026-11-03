// The Web Worker that runs Pomona's real Python (Pyodide) for the page. Nothing here uses the network except reading
// this Space's own files at start-up. Requests: {id, type, body}. Answers: {id, result} or {id, error, refused}.
//   type "info"  the tricks, zones, verdict table and build commit
//   type "act"   {scenario?, seed?, commands?, advance?} -> {scenario, view}; a scenario that is not the live session
//                is rebuilt in slices, reporting {id, type: "progress", phase: "rebuild", tick, total}
// Start-up messages (no id): {type: "progress", phase: "load", fraction, text}, {type: "ready"}, {type: "fatal", error}.
import { loadPyodide } from "./pyodide/pyodide.mjs";
import { boot } from "./boot.js";

const post = (message) => self.postMessage(message);
const here = (path) => new URL(path, import.meta.url);

async function readBytes(path) {
  const response = await fetch(here(path));
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return new Uint8Array(await response.arrayBuffer());
}

let handle = null;
const ready = boot({
  loadPyodide,
  indexURL: here("pyodide/").href,
  readBytes,
  progress: (fraction, text) => post({ type: "progress", phase: "load", fraction, text }),
}).then((py) => {
  handle = py.pyimport("engine_api").handle;
  post({ type: "ready" });
}).catch((error) => {
  post({ type: "fatal", error: String(error && error.message || error) });
  throw error;
});
ready.catch(() => {});  // each queued request reports the failure itself

class Refused extends Error {}

/** One call into engine_api.handle: JSON text in, JSON text out. A refused request throws Refused. */
function call(kind, body) {
  const answer = JSON.parse(handle(kind, body === undefined ? "" : JSON.stringify(body)));
  if (answer.error) throw new Refused(answer.error);
  return answer.result;
}

function act(id, body) {
  if (body && body.scenario) {
    const plan = call("begin", body);
    for (let more = plan.rebuild; more;) {
      const step = call("step");
      post({ id, type: "progress", phase: "rebuild", tick: step.tick, total: step.total });
      more = !step.done;
    }
  }
  return call("act", body);
}

let queue = Promise.resolve();  // one request at a time, in order
self.onmessage = ({ data: { id, type, body } }) => {
  queue = queue.then(async () => {
    try {
      await ready;
      const result = type === "info" ? call("info") : type === "act" ? act(id, body) : (() => { throw new Refused("unknown request"); })();
      post({ id, result });
    } catch (error) {
      const refused = error instanceof Refused;
      post({ id, error: refused ? error.message : "Pomona's engine stopped unexpectedly: " + String(error && error.message || error).trim().split("\n").pop(), refused });
    }
  });
};
