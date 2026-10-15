"""Coefficients derived from geometry and atmosphere behave as the physics
says they must, and become a project the planner accepts."""
import copy
import json

import pytest

from tools.restoration_demo import physical_district
from vdl7.cli import main
from vdl7.derive import derive, luminance_mcd, read
from vdl7.restore import ProjectError, solve
from vdl7.skyglow import CELL_RADIUS_M, Atmosphere, _cell_kernel, area_kernel


def one_emitter(change=None, **emitter):
    """One source, two places (near and 15 km away), clear and hazy air."""
    e = {"x_m": 0, "y_m": 0, "radius_m": 100, "lumens": 1e6, "uplight_fraction": 0.1, "reflectance": 0.15}
    e.update(emitter)
    return {"schema": "nocturne-physical/1", "title": "One emitter", "synthetic": True, "evidence": "test",
            "budget_usd": 1000, "coordinates": "local_m",
            "receptors": [{"id": "near", "label": "Near", "target_mcd_m2": 10, "x_m": 500, "y_m": 0},
                          {"id": "far", "label": "Far", "target_mcd_m2": 10, "x_m": 15000, "y_m": 0}],
            "conditions": [{"id": "clear", "label": "Clear", "aod_550": 0.08, "unmanaged_mcd_m2": 0.2},
                           {"id": "hazy", "label": "Hazy", "aod_550": 0.6, "unmanaged_mcd_m2": 0.3}],
            "sources": [{"id": "lamp", "label": "Lamp", "owner": "test", "authorized": True,
                         "minimum_service_fraction": 0, "spectrum": "3000K", "emitters": [e],
                         "options": [{"id": "change", "label": "Change", "cost_usd": 10, "service_fraction": 1,
                                      "reviewed": True, "evidence": "test", "change": change or {"output_factor": 0.5}}]}]}


def contributions(project, scenario):
    sc = next(s for s in project["scenarios"] if s["id"] == scenario)
    return sc["contributions_mcd_m2"]["lamp"]


def fractions(project):
    return project["sources"][0]["options"][0]["remaining_fraction"]


def test_area_kernel_is_the_grid_cell_kernel_at_the_cell_radius():
    atm = Atmosphere()
    for d in (0, 120, 900, 1884, 5000, 40000):
        assert area_kernel(d, CELL_RADIUS_M, "iso", "A", atm) == _cell_kernel(d, "iso", "A", atm)


def test_dimming_leaves_exactly_its_output_everywhere():
    f = fractions(derive(one_emitter({"output_factor": 0.37})))
    assert f == {"clear": 0.37, "hazy": 0.37}                     # radiative transfer is linear in its sources


def test_contributions_scale_with_lumens():
    a, b = derive(one_emitter(lumens=1e6)), derive(one_emitter(lumens=2e6))
    for scenario in ("clear", "hazy"):
        for place in ("near", "far"):
            assert contributions(b, scenario)[place] == pytest.approx(2 * contributions(a, scenario)[place], rel=1e-5)


def test_shielding_depends_on_distance_and_on_the_air():
    f = fractions(derive(one_emitter({"uplight_fraction": 0.0}, uplight_fraction=0.2)))
    assert f["clear"]["far"] < f["clear"]["near"] < 1              # in clear air low-angle uplight travels furthest
    assert f["hazy"]["far"] > f["clear"]["far"]                    # haze extinguishes those long low paths
    assert f["hazy"]["near"] < f["clear"]["near"]                  # and scatters more of the uplight close by


def test_haze_brightens_near_skies_and_darkens_distant_ones():
    p = derive(one_emitter())
    assert contributions(p, "hazy")["near"] > contributions(p, "clear")["near"]
    assert contributions(p, "hazy")["far"] < contributions(p, "clear")["far"]


def test_snow_raises_reflected_light_and_weakens_shielding():
    plain = one_emitter({"uplight_fraction": 0.0}, uplight_fraction=0.2)
    snowy = copy.deepcopy(plain)
    for c in snowy["conditions"]:
        c["reflectance_multiplier"] = 4.0
    a, b = derive(plain), derive(snowy)
    assert contributions(b, "clear")["near"] > contributions(a, "clear")["near"]
    assert fractions(b)["clear"]["near"] > fractions(a)["clear"]["near"]   # more of the light is reflected, not direct


def test_warmer_spectrum_scatters_less_per_lumen():
    f = fractions(derive(one_emitter({"spectrum": "2200K"})))
    assert all(v < 1 for scenario in f.values() for v in (scenario.values() if isinstance(scenario, dict) else [scenario]))


def test_calibration_range_becomes_contribution_ranges():
    physical = one_emitter()
    physical["calibration_factor"] = [0.5, 2.0]
    project = derive(physical)
    low, central, high = contributions(project, "clear")["near"]
    assert high == pytest.approx(4 * low, rel=1e-5) and central == pytest.approx(2.5 * low, rel=1e-5)
    assert solve(project)["uncertainty"]["ranged_values"] > 0


def test_example_derives_a_plannable_project_with_provenance():
    project = derive(physical_district())
    assert project["schema_version"] == 2 and project["provenance"]["derived_by"] == "nocturne derive"
    assert project["provenance"]["limits"]
    result = solve(project)
    assert result["status"] == "feasible"
    assert result["uncertainty"]["cost_of_uncertainty_usd"] > 0
    assert any(k["active"] for k in result["interactions"])
    streets = next(s for s in project["sources"] if s["id"] == "streets")
    shield = next(o for o in streets["options"] if o["id"] == "shield-and-schedule")
    assert isinstance(shield["remaining_fraction"]["clear"], dict)          # directional, not one number
    assert shield["remaining_fraction"]["snow"]["park"] > shield["remaining_fraction"]["clear"]["park"]


def test_physical_errors_are_listed_with_paths():
    physical = one_emitter({"spectrum": "purple"})
    physical["conditions"][0]["aod_550"] = -1
    del physical["receptors"][1]["x_m"]
    with pytest.raises(ProjectError) as e:
        read(physical)
    paths = [p for p, _ in e.value.problems]
    assert "sources[lamp].options[change].change.spectrum" in paths
    assert "conditions[clear].aod_550" in paths
    assert any(p == "receptors[far]" for p in paths)


def test_a_change_that_floods_one_place_with_light_is_refused():
    with pytest.raises(ProjectError, match="more than 10x"):
        derive(one_emitter({"uplight_fraction": 1.0}, uplight_fraction=0.0, reflectance=0.01))


def test_latlon_coordinates_match_local_metres():
    local = one_emitter()
    geo = copy.deepcopy(local)
    geo["coordinates"] = "latlon"
    for r, lon in zip(geo["receptors"], (-77.0 + 500 / 86_700, -77.0 + 15000 / 86_700)):
        del r["x_m"], r["y_m"]
        r["lat"], r["lon"] = 38.9, lon
    e = geo["sources"][0]["emitters"][0]
    del e["x_m"], e["y_m"]
    e["lat"], e["lon"] = 38.9, -77.0
    a, b = derive(local), derive(geo)
    assert contributions(b, "clear")["near"] == pytest.approx(contributions(a, "clear")["near"], rel=0.01)


def test_cli_derive_then_restore(tmp_path, capsys):
    physical = tmp_path / "physical.json"
    physical.write_text(json.dumps(physical_district()))
    project = tmp_path / "project.json"
    assert main(["derive", str(physical), "--out", str(project)]) == 0
    assert "remaining fractions" in capsys.readouterr().out
    assert main(["derive", str(physical), "--out", str(project)]) == 2            # never overwrites
    capsys.readouterr()
    assert main(["restore", str(project), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "feasible"
    assert main(["check", str(project)]) == 0
    assert "ready to plan" in capsys.readouterr().out


def test_luminance_is_zero_without_light():
    condition = {"aod_550": 0.1, "aerosol_scale_height_m": 1500, "single_scattering_albedo": 0.9, "asymmetry": 0.7,
                 "reflectance_multiplier": 1.0}
    emitter = {"at": (0, 0), "radius_m": 50, "lumens": 0, "uplight": 0.5, "reflectance": 0.2}
    assert luminance_mcd([emitter], "3000K", condition, (100, 0), "local_m") == 0


def test_check_on_a_physical_district_reports_option_errors(tmp_path, capsys):
    physical = one_emitter()
    option = physical["sources"][0]["options"][0]
    option.update(cost_usd="1,200", reviewed="yes")
    physical["sources"][0]["options"].append(dict(option))
    path = tmp_path / "physical.json"
    path.write_text(json.dumps(physical))
    assert main(["check", str(path)]) == 2
    out = capsys.readouterr().out
    assert "cost_usd" in out and "reviewed" in out and "duplicate id" in out
    with pytest.raises(ProjectError, match="duplicate"):
        read(physical)


def test_many_conditions_reuse_each_atmosphere(monkeypatch):
    import vdl7.skyglow as skyglow
    physical = one_emitter({"uplight_fraction": 0.0})
    physical["conditions"] = [{"id": f"c{i}", "label": f"C{i}", "aod_550": 0.05 + 0.04 * i, "unmanaged_mcd_m2": 0.2}
                              for i in range(12)]
    skyglow._kernels.cache_clear()
    derive(physical)
    assert skyglow._kernels.cache_info().misses == 12               # one kernel table per atmosphere, never rebuilt
