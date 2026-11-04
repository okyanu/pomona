"""The static Space: its files, the page's security policy, the README front matter, and the info the page shows."""

import re
import zipfile

import engine_api
import game
from helpers import SPACE

PLAN_VERDICTS = ["caught", "caught_cant_confirm", "missed", "caught_at_recovery", "wrong_card", "no_card_rule", "too_short_to_raise",
                 "undetectable", "false_alarm"]
PAGE = (SPACE / "index.html").read_text()


def front_matter():
    text = (SPACE / "README.md").read_text()
    block = re.match(r"---\n(.*?)\n---\n", text, re.S).group(1)
    scalars = dict(re.findall(r"^([A-Za-z_]+): (.+)$", block, re.M))
    return block, scalars


def test_the_space_is_static_and_the_readme_front_matter_is_in_order():
    block, meta = front_matter()
    assert meta["sdk"] == "static" and meta.get("app_file", "index.html") == "index.html"
    assert "app_port" not in meta and "docker" not in block.lower()
    assert len(meta["short_description"]) <= 60, len(meta["short_description"])
    assert meta["license"] == "apache-2.0" and meta["title"] == "Try to fool Pomona"
    for key in ("emoji", "colorFrom", "colorTo"):
        assert key in meta
    assert "Okyanus/pomona-tomato-risk-reasoner-v0.1.7-lora" in block and "Okyanus/greenhouse-sensor-data" in block
    for tag in ("agriculture", "sensors", "greenhouse", "hydroponics", "tomato", "fault-injection"):
        assert f"- {tag}" in block


def test_no_server_files_are_left():
    for name in ("Dockerfile", ".dockerignore", "server.py", "requirements.txt", "requirements-dev.txt"):
        assert not (SPACE / name).exists(), name
    assert not (SPACE / "static").exists()
    readme = (SPACE / "README.md").read_text()
    assert "uvicorn" not in readme and "docker run" not in readme and "Dockerfile" not in readme


def test_the_files_the_page_loads_exist_and_it_loads_nothing_from_other_hosts():
    for path in re.findall(r'(?:src|href)="([^":#]+)"', PAGE):
        assert (SPACE / path).is_file(), path
    assert not re.search(r'(?:src|href)="https?://(?!github\.com|huggingface\.co)', PAGE), "no outside scripts or styles"
    assert '<script src="app.js"' in PAGE and "<style" not in PAGE and " style=" not in PAGE
    assert (SPACE / "worker.js").is_file() and (SPACE / "boot.js").is_file()
    assert 'new Worker("worker.js", { type: "module" })' in (SPACE / "app.js").read_text()
    for path in ("app.js", "worker.js", "boot.js", "style.css"):
        text = (SPACE / path).read_text()
        assert not re.search(r"(?:src|url\()\s*[\"']?https?://", text), path
        assert not re.search(r"(?:import|fetch)\s*\(?\s*[\"']https?://", text), path
        assert "innerHTML" not in text and "eval(" not in text, path


def test_the_content_security_policy_meta_allows_only_this_space_and_wasm():
    tag = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', PAGE)
    assert tag, "the page needs its CSP <meta>"
    policy = dict(part.strip().split(" ", 1) for part in tag.group(1).split(";") if part.strip())
    assert policy["default-src"] == "'self'"
    assert policy["script-src"] == "'self' 'wasm-unsafe-eval'"
    assert policy["worker-src"] == "'self'"
    assert policy["connect-src"] == "'self'"
    assert policy["style-src"] == "'self'" and policy["img-src"] == "'self' data:"
    assert policy["base-uri"] == "'none'" and policy["form-action"] == "'none'"
    assert "unsafe-eval" not in tag.group(1).replace("wasm-unsafe-eval", "") and "unsafe-inline" not in tag.group(1)
    assert "http:" not in tag.group(1) and "https:" not in tag.group(1) and "*" not in tag.group(1)


def test_the_page_says_it_runs_in_the_browser_and_sends_nothing():
    text = " ".join(PAGE.split())
    assert "Pyodide" in text and "in your browser" in text and "Nothing you do here is sent to any server" in text
    assert "9 MB" in text and "first visit only" in text
    assert "stored on the server" not in text


def test_the_zip_the_worker_unpacks_has_the_engine_and_the_entry_point():
    with zipfile.ZipFile(SPACE / "pomona.zip") as archive:
        names = set(archive.namelist())
    assert {"game.py", "engine_api.py", "vendor/BUILD_INFO.json", "vendor/examples/simulators/inprocess_pomona.py",
            "vendor/services/automation-engine/app/rules.yaml"} <= names
    assert not any("__pycache__" in n or n.endswith(".pyc") for n in names)
    assert (SPACE / "game.py").read_bytes() == zipfile.ZipFile(SPACE / "pomona.zip").read("game.py")


def test_info_lists_the_tricks_the_zones_and_the_verdict_table():
    info = engine_api.Engine().info()
    assert {t["name"] for t in info["tricks"]} == set(game.TRICKS)
    assert [z["letter"] for z in info["zones"]] == ["A", "B"]
    codes = [v["code"] for v in info["verdicts"]]
    assert codes[: len(PLAN_VERDICTS)] == PLAN_VERDICTS
    plan_text = {v["code"]: v for v in info["verdicts"]}
    assert plan_text["no_card_rule"]["headline"].startswith("You fooled Pomona")
    assert plan_text["undetectable"]["headline"].startswith("Unfair trick")
    assert plan_text["false_alarm"]["headline"] == "Pomona cried wolf"
    assert plan_text["caught_at_recovery"]["scorer"].startswith("MISSED") and "fooled Pomona" in plan_text["caught_at_recovery"]["headline"]
    assert plan_text["caught_cant_confirm"]["headline"] == "Pomona couldn't confirm it and asked for a meter check"
    assert all(v["doc"].startswith("https://github.com/okyanu/pomona/blob/main/docs/") and v["why"] for v in info["verdicts"])
    dry = next(t for t in info["tricks"] if t["name"] == "dry_zone")
    assert dry["zones"] == ["greenhouse-a"]
    assert info["caps"]["max_hours"] == 24 and info["windows"]["default_min"] == 10
    assert info["build"]["short_commit"] and len(info["build"]["short_commit"]) == 7
