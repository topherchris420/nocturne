"""The browser planner: local only, token and Host checked, writes only its
own file (with a backup), and gives the same answers as the command line."""
import http.client
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tools.restoration_demo import district, physical_district
from vdl7.app import MAX_BODY, start
from vdl7.restore import solve

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def served(tmp_path):
    servers = []

    def launch(path=None):
        server, url, session = start(path)
        servers.append(server)
        port = server.server_address[1]

        def call(method, route, body=None, token=session.token, host=f"127.0.0.1:{port}", content_type="application/json",
                 length=None):
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=30)
            headers = {"Host": host}
            if token:
                headers["X-Nocturne-Token"] = token
            data = None
            if body is not None:
                data = body if isinstance(body, bytes) else json.dumps(body).encode()
                headers["Content-Type"] = content_type
            if length is not None:                   # declare a size without sending it: refused before reading
                headers["Content-Length"] = str(length)
            conn.request(method, route, body=data, headers=headers)
            res = conn.getresponse()
            raw = res.read()
            conn.close()
            kind = res.getheader("Content-Type", "")
            return res.status, (json.loads(raw) if kind.startswith("application/json") else raw.decode()), res

        return call, url, session
    yield launch
    for s in servers:
        s.shutdown()
        s.server_close()


def test_page_is_served_with_a_strict_policy(served):
    call, url, _ = served()
    assert url.startswith("http://127.0.0.1:") and "#token=" in url           # the token never reaches a server log
    status, page, res = call("GET", "/", token=None)
    assert status == 200 and "Nocturne Planner" in page
    assert "default-src 'none'" in res.getheader("Content-Security-Policy")


def test_data_needs_the_session_token_and_a_local_host(served):
    call, _, _ = served()
    assert call("GET", "/api/session", token=None)[0] == 403
    assert call("GET", "/api/session", token="guess")[0] == 403
    assert call("POST", "/api/check", {"project": district()}, token=None)[0] == 403
    # A page elsewhere that rebinds its DNS name to 127.0.0.1 sends its own Host header.
    assert call("GET", "/api/session", host="evil.example")[0] == 403
    assert call("GET", "/", host="evil.example")[0] == 403
    assert call("GET", "/api/session")[0] == 200


def test_requests_must_be_json_and_bounded(served):
    call, _, _ = served()
    assert call("POST", "/api/check", b"{}", content_type="text/plain")[0] == 415
    assert call("POST", "/api/check", b"not json")[0] == 400
    assert call("POST", "/api/check", b"[]")[0] == 400
    assert call("POST", "/api/check", b"{}", length=MAX_BODY + 1)[0] == 413


def test_answers_match_the_command_line(served):
    call, _, _ = served()
    status, result, _ = call("POST", "/api/solve", {"project": district(), "budget_usd": 1000})
    expected = solve(district(), 1000)
    assert status == 200 and result["status"] == "budget_shortfall"
    assert result["actions"] == expected["actions"] and result["receptors"] == expected["receptors"]
    status, page, _ = call("POST", "/api/report", {"project": district()})
    assert status == 200 and "restoration brief" in page
    status, report, _ = call("POST", "/api/check", {"project": district()})
    assert status == 200 and report["ok"] and report["warnings"]


def test_problems_come_back_with_paths(served):
    call, _, _ = served()
    project = district()
    project["receptors"][0]["target_mcd_m2"] = -1
    status, body, _ = call("POST", "/api/solve", {"project": project})
    assert status == 422 and body["problems"][0]["path"] == "receptors[park].target_mcd_m2"
    status, body, _ = call("POST", "/api/check", {"project": project})
    assert status == 200 and not body["ok"]


def test_examples_and_derivation(served):
    call, _, _ = served()
    status, session, _ = call("GET", "/api/session")
    assert {x["id"] for x in session["examples"]} >= {"blank", "district", "derived"}
    assert session["writable"] is False and session["project"] is None
    for example in ("blank", "district", "derived"):
        status, project, _ = call("GET", f"/api/example/{example}")
        assert status == 200 and call("POST", "/api/check", {"project": project})[1]["ok"], example
    status, derived, _ = call("POST", "/api/derive", {"physical": physical_district()})
    assert status == 200 and derived["provenance"]["derived_by"] == "nocturne derive"


def test_saves_only_to_its_own_file_and_keeps_a_backup(served, tmp_path):
    call, _, _ = served()
    assert call("POST", "/api/save", {"project": district()})[0] == 409          # no file: download instead
    path = tmp_path / "plan.json"
    shutil.copy(ROOT / "examples/restoration/district.json", path)
    call, _, session = served(path)
    status, s, _ = call("GET", "/api/session")
    assert s["writable"] and s["file"] == "plan.json" and s["project"]["title"] == district()["title"]
    changed = district()
    changed["title"] = "Edited in the browser"
    status, body, _ = call("POST", "/api/save", {"project": changed, "path": "/etc/passwd"})
    assert status == 200 and body == {"saved": "plan.json", "backup": "plan.json.bak"}
    assert json.loads(path.read_text())["title"] == "Edited in the browser"
    assert json.loads((tmp_path / "plan.json.bak").read_text())["title"] == district()["title"]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["plan.json", "plan.json.bak"]   # no temp files left


def test_a_new_file_is_created_on_first_save(served, tmp_path):
    path = tmp_path / "new.json"
    call, _, _ = served(path)
    status, s, _ = call("GET", "/api/session")
    assert s["writable"] and "does not exist yet" in s["notice"] and call("POST", "/api/check", {"project": s["project"]})[1]["ok"]
    assert call("POST", "/api/save", {"project": s["project"]})[1]["backup"] is None
    assert path.exists()


def test_a_physical_district_is_derived_and_never_overwritten(served, tmp_path):
    path = tmp_path / "physical.json"
    path.write_text(json.dumps(physical_district()))
    call, _, _ = served(path)
    status, s, _ = call("GET", "/api/session")
    assert not s["writable"] and "physical district" in s["notice"] and s["project"]["schema_version"] == 2
    assert call("POST", "/api/save", {"project": s["project"]})[0] == 409


NODE = shutil.which("node")


@pytest.mark.skipif(NODE is None, reason="Node.js not installed")
def test_value_cells_parse_numbers_and_ranges():
    page = (ROOT / "vdl7/planner.html").read_text()
    code = re.search(r"// <values>.*?\n(.*?)// </values>", page, re.S).group(1)
    probe = code + """
const cases = ["0.4", " .5 ", "0.3 – 0.5", "0.3-0.5", "0.3 to 0.5", "0.2 / 0.3 / 0.6", "0.5 – 0.3", "-1", "abc", "",
               "0.3..0.3", "1e-3", "0.1 – 0.2 – 0.3 – 0.4"];
const out = cases.map((c) => parseValue(c));
out.push(parseValue("-0.05 to 0.02", { negative: true }), parseValue("0.3 – 0.5", { range: false }),
         parseMoney("$2,400.50"), parseMoney("2.001"), formatValue([0.3, 0.5]), formatValue(0.1 + 0.2),
         slug("Office windows!", ["office-windows"]), slug("keep", []));
console.log(JSON.stringify(out));
"""
    out = json.loads(subprocess.run([NODE, "-e", probe], capture_output=True, text=True, check=True).stdout)
    assert out[0] == {"value": 0.4} and out[1] == {"value": 0.5}
    assert out[2] == out[3] == out[4] == {"value": [0.3, 0.5]}
    assert out[5] == {"value": [0.2, 0.3, 0.6]}
    assert "low to high" in out[6]["error"] and "negative" in out[7]["error"]
    assert "error" in out[8] and "error" in out[9]
    assert out[10] == {"value": 0.3} and out[11] == {"value": 0.001} and "error" in out[12]
    assert out[13] == {"value": [-0.05, 0.02]} and "single number" in out[14]["error"]
    assert out[15] == {"value": 2400.5} and "error" in out[16]
    assert out[17] == "0.3 – 0.5" and out[18] == "0.3"
    assert out[19] == "office-windows-2" and out[20] == "keep-2"
