"""Helpers the Space tests share."""

from pathlib import Path

SPACE = Path(__file__).resolve().parents[1]


def act(client, **body):
    response = client.post("/api/act", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def play(client, steps, seed=11):
    """Drive a session like the page does. steps: ('cmd', {command}) runs it plus one tick, ('ff', ticks) fast-forwards."""
    result = act(client, seed=seed)
    for kind, arg in steps:
        if kind == "cmd":
            result = act(client, scenario=result["scenario"], commands=[arg], advance=1)
        else:
            result = act(client, scenario=result["scenario"], advance=arg)
    return result


A, B = "greenhouse-a", "greenhouse-b"
START = lambda name, zone, field=None: {"op": "start", "name": name, "zone": zone, **({"field": field} if field else {})}  # noqa: E731
STOP = lambda name, zone, field=None: {"op": "stop", "name": name, "zone": zone, **({"field": field} if field else {})}  # noqa: E731
CAL = lambda zone, field: {"op": "calibrate", "zone": zone, "field": field}  # noqa: E731
