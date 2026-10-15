"""A portable, script-free stakeholder brief for a restoration result."""
from html import escape

STATUS_TEXT = {"met": "MET", "uncertain": "UNCERTAIN", "not_met": "NOT MET"}


def _term(term, labels):
    if term == "unmanaged":
        return "light no listed owner controls"
    if term.startswith("interaction:"):
        return "interaction: " + term.split(":", 1)[1]
    return labels.get(term, term)


def render(result):
    e = lambda value: escape(str(value), quote=True)
    label = "Synthetic example · all inputs invented" if result["synthetic"] else "Conditional planning model · field verification required"
    statuses = {"feasible": "Every modeled target can be reached.", "budget_shortfall": "The target needs a larger budget.",
                "outside_available_actions": "The target needs additional actions or participants."}
    labels = result.get("source_labels") or {a["source"]: a["source_label"] for a in result["actions"]}
    uncertainty = result.get("uncertainty", {"ranged_values": 0})
    ranged = uncertainty["ranged_values"]
    rows = result["receptors"]
    met = sum(1 for r in rows if r.get("target_status", "met" if r["meets_target"] else "not_met") == "met")
    cards = []
    for r in rows:
        base = r["baseline_mcd_m2"]
        pct = (lambda v: max(0.0, min(100.0, 100 * v / base))) if base else (lambda v: 0.0)
        lo, hi = r.get("remaining_range_mcd_m2", [r["remaining_mcd_m2"]] * 2)
        status = r.get("target_status", "met" if r["meets_target"] else "not_met")
        band = (f'<i class="band" style="left:{pct(lo):.3f}%;width:{max(0.0, pct(hi) - pct(lo)):.3f}%"></i>'
                if hi - lo > 1e-9 else "")
        headroom = r.get("headroom_fraction")
        detail = []
        if status == "met" and headroom is not None:
            detail.append(f"{headroom:.0%} headroom: still met if all remaining light were {headroom:.0%} brighter")
        elif status == "uncertain":
            detail.append("met only at the optimistic end of the ranges")
        if "dominant_term" in r:
            detail.append(f"largest remaining: {_term(r['dominant_term']['term'], labels)}")
        span = f" (range {lo:.3f}–{hi:.3f})" if hi - lo > 1e-9 else ""
        cards.append(f'<article class="{status}"><div class="eyebrow">{e(r["scenario"])}</div><h3>{e(r["label"])}</h3>'
                     f'<div class="bar" role="img" aria-label="{e(r["label"])}: {r["remaining_mcd_m2"]:.3f} of {base:.3f} '
                     f'mcd/m² remaining; target {r["target_mcd_m2"]:.3f}"><span style="width:{pct(r["remaining_mcd_m2"]):.3f}%"></span>'
                     f'{band}<b class="target" style="left:{pct(r["target_mcd_m2"]):.3f}%"></b></div>'
                     f'<p><strong>{r["remaining_mcd_m2"]:.3f}</strong> from {base:.3f} mcd/m²{e(span)}</p>'
                     f'<p>Target ≤ {r["target_mcd_m2"]:.3f} · <b>{STATUS_TEXT[status]}</b></p>'
                     + "".join(f'<p class="detail">{e(d)}</p>' for d in detail) + '</article>')
    actions = "".join(f'<tr><td>{e(a["source_label"])}<small>{e(a["owner"])}</small></td><td>{e(a["label"])}'
                      f'<small>{e(a["evidence"])}</small></td><td>${a["cost_usd"]:,.2f}</td></tr>' for a in result["actions"])
    if not actions:
        actions = '<tr><td colspan="3">Keep current operation; no intervention selected.</td></tr>'
    exclusions = "".join(f'<li>{e(a["source"])} / {e(a["option"])}: {e("; ".join(a["reasons"]))}</li>' for a in result["excluded_options"])
    minimum = result["minimum_feasible_cost_usd"]
    minimum_text = "No combination of available actions meets every target." if minimum is None else f"Minimum modeled cost to meet every target: ${minimum:,.2f}."
    sections = []
    if ranged:
        central = uncertainty.get("central_plan", {})
        lines = [f"{ranged} input value{'s are' if ranged > 1 else ' is a'} range{'s' if ranged > 1 else ''}. "
                 "Every target is checked at the pessimistic end of every range; the shaded band on each bar spans "
                 "the optimistic to pessimistic result."]
        if uncertainty.get("cost_of_uncertainty_usd") == 0:
            lines.append("The ranges do not change the price: central values give a plan of the same cost.")
        elif uncertainty.get("cost_of_uncertainty_usd") is not None:
            lines.append(f"On central values the cheapest plan would cost ${central['cost_usd']:,.2f}. Planning for the "
                         f"pessimistic case costs ${uncertainty['cost_of_uncertainty_usd']:,.2f} more: that is what better "
                         "measurement of the largest remaining terms could save.")
        elif central.get("status") == "not_computed":
            lines.append(f"No plan was computed on central values: {central.get('reason', '')}")
        elif central:
            lines.append(f"On central values alone the planner's status would be: {central.get('status', 'unknown').replace('_', ' ')}.")
        sections.append("<h2>What uncertainty costs</h2>" + "".join(f"<p>{e(x)}</p>" for x in lines))
    interactions = result.get("interactions", [])
    if interactions:
        items = "".join(f'<li><b>{"In effect" if k["active"] else "Not triggered"}</b>: {e(k["label"])}'
                        f'<small>{e(k["evidence"])}</small></li>' for k in interactions)
        sections.append("<h2>Where effects do not simply add</h2><p>Declared interactions between options, such as a rebound "
                        "when one owner dims or a shared reflecting surface, are charged to the plans that trigger them.</p>"
                        f"<ul>{items}</ul>")
    provenance = result.get("provenance")
    if isinstance(provenance, dict) and provenance.get("derived_by"):
        limits = "".join(f"<li>{e(x)}</li>" for x in provenance.get("limits", []))
        sections.append(f"<h2>Where the coefficients came from</h2><p>{e(provenance['derived_by'])}: {e(provenance.get('method', ''))}. "
                        f"Calibration factor: {e(provenance.get('calibration_factor', 1))}.</p><ul>{limits}</ul>")
    return f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nocturne — {e(result['title'])}</title>
<style>
:root{{color-scheme:dark;--ink:#f3f4ee;--muted:#b2c7c8;--teal:#73d5c8;--line:#29424a;--warn:#f0b454;--bad:#ff8a80}}
*{{box-sizing:border-box}}body{{margin:0;background:#0b181e;color:var(--ink);font:17px/1.6 system-ui,sans-serif}}
main{{max-width:1120px;margin:auto;padding:64px 28px}}.eyebrow{{color:var(--teal);font-size:12px;letter-spacing:.13em;text-transform:uppercase}}
h1{{font-size:clamp(38px,6vw,68px);line-height:1.08;font-weight:550;max-width:900px;margin:18px 0 28px}}h2{{font-size:26px;margin:42px 0 18px}}h3{{margin:8px 0;font-size:21px}}
p{{max-width:830px}}.lede{{font-size:22px;color:var(--muted)}}.notice{{border-left:3px solid var(--teal);padding:10px 18px;background:#122b30}}
.stats{{display:flex;flex-wrap:wrap;gap:50px;padding:26px 0;border-bottom:1px solid var(--line)}}.stats strong{{font-size:34px;display:block}}small{{display:block;color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}article{{padding:24px;background:#13262d;border:1px solid var(--line);border-radius:12px}}article p{{margin:8px 0}}
article.uncertain{{border-color:var(--warn)}}article.not_met{{border-color:var(--bad)}}.detail{{color:var(--muted);font-size:15px}}
.bar{{position:relative;height:12px;border-radius:6px;background:#4d6771;margin:20px 0}}.bar span{{display:block;height:100%;border-radius:6px;background:var(--teal)}}
.bar .band{{position:absolute;top:0;height:100%;background:repeating-linear-gradient(45deg,#ffffff55 0 3px,transparent 3px 6px)}}
.bar .target{{position:absolute;top:-5px;width:2px;height:22px;background:var(--ink)}}
.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;text-align:left}}td,th{{padding:16px 12px;border-bottom:1px solid var(--line);vertical-align:top}}td:last-child{{white-space:nowrap}}
li{{margin:10px 0;color:var(--muted)}}li b{{color:var(--ink)}}code{{overflow-wrap:anywhere;font-size:12px}}footer{{border-top:1px solid var(--line);margin-top:50px;padding-top:20px;color:var(--muted)}}
@media print{{:root{{color-scheme:light;--ink:#12232a}}body{{background:white;color:#12232a}}main{{padding:20px}}article,.notice{{background:#eef5f4}}.lede,small,li,footer,.detail{{color:#314c54}}article{{break-inside:avoid}}.bar .band{{background:repeating-linear-gradient(45deg,#00000044 0 3px,transparent 3px 6px)}}}}
</style><main><div class="eyebrow">Nocturne / restoration brief</div>
<h1>{e(statuses[result['status']])}</h1><p class="lede">{e(result['title'])}</p>
<p class="notice">{e(label)}. Planning only; this report does not operate lights.</p>
<div class="stats"><div><strong>${result['cost_usd']:,.0f}</strong>Selected package cost</div><div><strong>${result['budget_usd']:,.0f}</strong>Available budget</div><div><strong>{len(result['actions'])}</strong>Source interventions</div><div><strong>{met} of {len(rows)}</strong>Targets met{' in the pessimistic case' if ranged else ''}</div></div>
<p>{e(minimum_text)}</p><h2>Protect every place, in every modeled condition</h2>
<p>Bars show artificial zenith sky brightness remaining relative to each baseline; the vertical mark is the target. Lower is darker. Natural sky brightness is excluded. These are modeled values, not field measurements.</p>
<div class="grid">{''.join(cards)}</div><h2>A named owner for every change</h2><div class="scroll"><table><thead><tr><th>Source / owner</th><th>Complete intervention / evidence</th><th>Cost</th></tr></thead><tbody>{actions}</tbody></table></div>
{''.join(sections)}
<h2>What the planner could not use</h2><ul>{exclusions or '<li>No options excluded by the declared eligibility checks.</li>'}</ul>
<h2>Prove the change, then plan again</h2><p>Preregister randomized baseline/dim windows for one consenting source group at a time. Compare a protected receptor with an unaffected control station. Retain failed windows, estimate the effect in linear luminance, and update only the source coefficients supported by those observations.</p>
<h2>Limits of this result</h2><ul>{''.join('<li>'+e(v)+'</li>' for v in result['limits'])}</ul>
<footer>Christopher Woodyard / Vers3Dynamics · Nocturne<br>{e(result['solver'])}: {result['candidate_portfolios']:,} portfolios.<br>Input fingerprint: <code>{e(result['project_sha256'])}</code></footer></main></html>'''
