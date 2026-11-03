"""Scripted sessions through the Space's engine, run by CPython and by Pyodide so the two can be compared byte for byte.

CPython (reference, a real asyncio loop):  python -I parity_driver.py SPACE_DIR DEMO_JSON OUT_JSON
Pyodide (SyncLoop, as in the browser):     parity_driver.run_all(space_dir, demo_path, sync=True) -> JSON text
"""
import json
import sys
import time


def jd(value):
    return json.dumps(value, sort_keys=True, default=str)


def readings_of(session):
    return {"frames": [[z, t, v] for (z, t), v in sorted(session.frame_info.items())], "alert_events": session.alert_events}


def scripted(game, steps, seed=11):
    s = game.Session.start_new(seed)
    for kind, arg in steps:
        if kind == "cmd":
            s.command(arg)
            s.advance(1)
        else:
            s.advance(arg)
    view = s.view()
    out = {"ticks": s.tick, "episodes": view["episodes"], "totals": view["totals"], "zones": view["zones"],
           "timeline": view["timeline"], "scenario": view["scenario"], "export": view["export"], **readings_of(s)}
    s.close()
    return out


def demo(game, ipp, fg, score, demo_path):
    """demo.json through the in-process engine and the repo's Grader, as the scorer does."""
    scenario = fg.load_scenario(demo_path)
    sim = fg.Simulation(seed=scenario["seed"], interval=game.TICK_S, sim_speed=1.0, start_hour=8.0,
                        clock=game.virtual_clock(), scenario=scenario)
    engine = ipp.InProcessPomona(game.RULES, game.DEFAULTS, loop=game.LOOP)
    frames, events, rows = {}, [], []
    for _ in range(scenario["duration_ticks"]):
        for reading in sim.step():
            truth, event = reading.truth, reading.event
            for item in truth.get("calibrations", []):
                engine.calibrate(truth["zone_id"], item["field"], item["at"], farm_id=sim.farm_id,
                                 device_id=truth["device_id"])
            fields = [f for f in sim.zones[truth["zone_id"]].cfg.sensors if f not in truth["placeholder_fields"]]
            sent = {"timestamp": event["timestamp"], **{f: event[f] for f in fields}} if event else None
            row = {"tick": truth["tick"], "zone_id": truth["zone_id"], "wall_timestamp": truth["wall_timestamp"],
                   "published": event is not None, "sent": sent, "expect": truth["expect"],
                   "active_faults": [{"name": f["name"], "field": f["field"], "source": f["source"]}
                                     for f in truth["active_faults"]],
                   "active_events": [{"name": e["name"], "source": e["source"]} for e in truth["active_events"]]}
            rows.append(row)
            if event is not None and score.core_accepted(row):
                got = engine.observe(event)
                frames[(truth["zone_id"], truth["tick"])] = {
                    "labels": got["labels"], "trust": got["trust"], "vetoed_fields": got["vetoed_fields"],
                    "card_labels": got["card_labels"], "sensor_check_labels": got["sensor_check_labels"]}
                events += got["alert_events"]
    grader = score.Grader(rows, events, game.RULES, game.DEFAULTS, frames)
    real = grader.real_episodes()
    faults = grader.fault_episodes(real)
    out = {"ticks": scenario["duration_ticks"], "frames": [[z, t, v] for (z, t), v in sorted(frames.items())],
           "alert_events": events, "real": real, "faults": faults, "false_alarms": grader.false_alarms(real, faults),
           "states": engine.states(sim.farm_id)}
    engine.close()
    return out


def worker_path(engine_api, scenario):
    """What worker.js does for a reload or a replay link: begin, step until done, then act, all as JSON text."""
    handle = engine_api.handle
    plan = json.loads(handle("begin", json.dumps({"scenario": scenario})))["result"]
    steps = 0
    while plan["rebuild"]:
        step = json.loads(handle("step"))["result"]
        steps += 1
        if step["done"]:
            break
    answer = json.loads(handle("act", json.dumps({"scenario": scenario, "commands": [
        {"op": "start", "name": "heat_spike", "zone": "greenhouse-a"}], "advance": 60})))["result"]
    return {"steps": steps, "scenario": answer["scenario"], "view": answer["view"]}


def run_all(space_dir, demo_path, sync=False, speed=False):
    t0 = time.perf_counter()
    sys.path.insert(0, space_dir)
    import game
    import engine_api
    import fake_greenhouse as fg
    import inprocess_pomona as ipp
    import score_fake_greenhouse as score
    timings = {"import_s": time.perf_counter() - t0}
    if sync:
        engine_api.install_sync_loop()
    A, B = "greenhouse-a", "greenhouse-b"
    START = lambda n, z, f=None: {"op": "start", "name": n, "zone": z, **({"field": f} if f else {})}
    STOP = lambda n, z, f=None: {"op": "stop", "name": n, "zone": z, **({"field": f} if f else {})}
    results = {}
    t = time.perf_counter()
    results["a_stuck_ph_B_40min"] = scripted(game, [("cmd", START("stuck", B, "ph")), ("ff", 79)])
    timings["a_s"] = time.perf_counter() - t
    t = time.perf_counter()
    results["b_heat_jump_stop_30min"] = scripted(game, [
        ("cmd", START("heat_spike", B)), ("cmd", START("jump", B, "ph")), ("ff", 120),
        ("cmd", STOP("heat_spike", B)), ("cmd", STOP("jump", B, "ph")), ("ff", 59)])
    timings["b_s"] = time.perf_counter() - t
    t = time.perf_counter()
    results["c_demo_json"] = demo(game, ipp, fg, score, demo_path)
    timings["c_s"] = time.perf_counter() - t
    t = time.perf_counter()
    played = scripted(game, [("cmd", START("jump", A, "ph")), ("ff", 240), ("cmd", STOP("jump", A, "ph")), ("ff", 240),
                             ("cmd", {"op": "hidden"}), ("ff", 100)], seed=5)
    results["d_worker_rebuild_path"] = worker_path(engine_api, played["scenario"])
    timings["d_s"] = time.perf_counter() - t
    if not speed:
        return json.dumps({"results_json": jd(results), "timings": timings, "python": sys.version})
    # speed (FOOL_PARITY_SPEED=1): a fresh +2 h click, one at simulated hour 20, and the rebuild of a whole 24 h session
    s = game.Session.start_new(5)
    t = time.perf_counter()
    s.advance(game.MAX_ADVANCE_TICKS)
    timings["ff_2h_fresh_s"] = time.perf_counter() - t
    s.advance(20 * 120 - s.tick)
    t = time.perf_counter()
    s.advance(game.MAX_ADVANCE_TICKS)
    timings["ff_2h_at_hour_20_s"] = time.perf_counter() - t
    t = time.perf_counter()
    s.advance(game.MAX_TICKS)
    s.view()
    scenario = s.scenario()
    s.close()
    timings["to_24h_and_view_s"] = time.perf_counter() - t
    engine = engine_api.Engine()
    t = time.perf_counter()
    plan = engine.begin({"scenario": scenario})
    slices, slice_s = 0, []
    while plan["rebuild"]:
        lap = time.perf_counter()
        step = engine.step()
        slice_s.append(time.perf_counter() - lap)
        slices += 1
        if step["done"]:
            break
    timings["rebuild_24h_s"] = time.perf_counter() - t
    timings["rebuild_slices"] = slices
    timings["rebuild_slowest_slice_s"] = max(slice_s)
    engine.close()
    return json.dumps({"results_json": jd(results), "timings": timings, "python": sys.version})


if __name__ == "__main__":
    space, demo_path, out = sys.argv[1:4]
    data = json.loads(run_all(space, demo_path, sync=len(sys.argv) > 4 and sys.argv[4] == "sync"))
    with open(out, "w") as handle:
        json.dump({"results_json": data["results_json"], "python": data["python"]}, handle)
    print("CPython reference written:", out, "(", len(data["results_json"]), "bytes of results )")
