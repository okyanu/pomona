"""Helpers the Space tests share."""

from pathlib import Path

import pytest

SPACE = Path(__file__).resolve().parents[1]


def act(engine, **body):
    return engine.act(body)


def refused(engine, **body):
    """The engine refuses this request; returns the visitor-safe message."""
    with pytest.raises(ValueError) as error:
        engine.act(body)
    assert str(error.value)
    return str(error.value)


def play(engine, steps, seed=11):
    """Drive a session like the page does. steps: ('cmd', {command}) runs it plus one tick, ('ff', ticks) fast-forwards."""
    result = act(engine, seed=seed)
    for kind, arg in steps:
        if kind == "cmd":
            result = act(engine, scenario=result["scenario"], commands=[arg], advance=1)
        else:
            result = act(engine, scenario=result["scenario"], advance=arg)
    return result


A, B = "greenhouse-a", "greenhouse-b"
START = lambda name, zone, field=None: {"op": "start", "name": name, "zone": zone, **({"field": field} if field else {})}  # noqa: E731
STOP = lambda name, zone, field=None: {"op": "stop", "name": name, "zone": zone, **({"field": field} if field else {})}  # noqa: E731
CAL = lambda zone, field: {"op": "calibrate", "zone": zone, "field": field}  # noqa: E731
