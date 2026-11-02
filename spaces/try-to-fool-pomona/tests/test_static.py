"""The page and the info endpoint."""

import re

import game

PLAN_VERDICTS = ["caught", "caught_cant_confirm", "missed", "wrong_card", "no_card_rule", "too_short_to_raise",
                 "undetectable", "false_alarm"]


def test_the_page_and_its_files_are_served_with_safe_headers(client):
    page = client.get("/")
    assert page.status_code == 200 and "Try to fool Pomona" in page.text
    assert "default-src 'self'" in page.headers["content-security-policy"]
    assert page.headers["x-content-type-options"] == "nosniff"
    for path in re.findall(r'(?:src|href)="(static/[^"]+)"', page.text):
        assert client.get("/" + path).status_code == 200, path
    assert not re.search(r'(?:src|href)="https?://(?!github\.com|huggingface\.co)', page.text), "no outside scripts or styles"
    assert '<script src="static/app.js"' in page.text and "<style" not in page.text and " style=" not in page.text


def test_no_external_hosts_are_loaded_by_the_scripts_or_styles(client):
    for path in ("static/app.js", "static/style.css"):
        text = client.get("/" + path).text
        assert not re.search(r"(?:src|url\()\s*[\"']?https?://", text), path
        assert "innerHTML" not in text


def test_info_lists_the_tricks_the_zones_and_the_verdict_table(client):
    info = client.get("/api/info").json()
    assert {t["name"] for t in info["tricks"]} == set(game.TRICKS)
    assert [z["letter"] for z in info["zones"]] == ["A", "B"]
    codes = [v["code"] for v in info["verdicts"]]
    assert codes[: len(PLAN_VERDICTS)] == PLAN_VERDICTS
    plan_text = {v["code"]: v for v in info["verdicts"]}
    assert plan_text["no_card_rule"]["headline"].startswith("You fooled Pomona")
    assert plan_text["undetectable"]["headline"].startswith("Unfair trick")
    assert plan_text["false_alarm"]["headline"] == "Pomona cried wolf"
    assert plan_text["caught_cant_confirm"]["headline"] == "Pomona couldn't confirm it and asked for a meter check"
    assert all(v["doc"].startswith("https://github.com/okyanu/pomona/blob/main/docs/") and v["why"] for v in info["verdicts"])
    dry = next(t for t in info["tricks"] if t["name"] == "dry_zone")
    assert dry["zones"] == ["greenhouse-a"]
    assert info["caps"]["max_hours"] == 24 and info["windows"]["default_min"] == 10
    assert client.get("/api/health").json() == {"ok": True}
    assert client.get("/api/info").headers["cache-control"] == "no-store"
