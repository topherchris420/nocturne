"""A portable, script-free stakeholder brief for a restoration result."""
from html import escape


def render(result):
    e = lambda value: escape(str(value), quote=True)
    label = "Synthetic example · all inputs invented" if result["synthetic"] else "Conditional planning model · field verification required"
    statuses = {"feasible": "Every modeled target can be reached.", "budget_shortfall": "The target needs a larger budget.",
                "outside_available_actions": "The target needs additional actions or participants."}
    cards = []
    for r in result["receptors"]:
        width = 100 * r["remaining_mcd_m2"] / r["baseline_mcd_m2"] if r["baseline_mcd_m2"] else 0
        cards.append(f'<article><div class="eyebrow">{e(r["scenario"])}</div><h3>{e(r["label"])}</h3>'
                     f'<div class="bar" aria-hidden="true"><span style="width:{width:.4f}%"></span></div>'
                     f'<p><strong>{r["remaining_mcd_m2"]:.3f}</strong> from {r["baseline_mcd_m2"]:.3f} mcd/m²</p>'
                     f'<p>Target ≤ {r["target_mcd_m2"]:.3f} · <b>{"MET" if r["meets_target"] else "NOT MET"}</b></p></article>')
    actions = "".join(f'<tr><td>{e(a["source_label"])}<small>{e(a["owner"])}</small></td><td>{e(a["label"])}</td>'
                      f'<td>${a["cost_usd"]:,.2f}</td></tr>' for a in result["actions"])
    if not actions:
        actions = '<tr><td colspan="3">Keep current operation; no intervention selected.</td></tr>'
    exclusions = "".join(f'<li>{e(a["source"])} / {e(a["option"])}: {e("; ".join(a["reasons"]))}</li>' for a in result["excluded_options"])
    minimum = result["minimum_feasible_cost_usd"]
    minimum_text = "No combination of available actions meets every target." if minimum is None else f"Minimum modeled cost to meet every target: ${minimum:,.2f}."
    return f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Nocturne — {e(result['title'])}</title>
<style>
:root{{color-scheme:dark;--ink:#f3f4ee;--muted:#b2c7c8;--teal:#73d5c8;--line:#29424a}}
*{{box-sizing:border-box}}body{{margin:0;background:#0b181e;color:var(--ink);font:17px/1.6 system-ui,sans-serif}}
main{{max-width:1120px;margin:auto;padding:64px 28px}}.eyebrow{{color:var(--teal);font-size:12px;letter-spacing:.13em;text-transform:uppercase}}
h1{{font-size:clamp(38px,6vw,68px);line-height:1.08;font-weight:550;max-width:900px;margin:18px 0 28px}}h2{{font-size:26px;margin:42px 0 18px}}h3{{margin:8px 0;font-size:21px}}
p{{max-width:830px}}.lede{{font-size:22px;color:var(--muted)}}.notice{{border-left:3px solid var(--teal);padding:10px 18px;background:#122b30}}
.stats{{display:flex;flex-wrap:wrap;gap:50px;padding:26px 0;border-bottom:1px solid var(--line)}}.stats strong{{font-size:34px;display:block}}small{{display:block;color:var(--muted)}}
.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:16px}}article{{padding:24px;background:#13262d;border:1px solid var(--line);border-radius:12px}}article p{{margin:8px 0}}
.bar{{height:12px;border-radius:6px;background:#4d6771;margin:20px 0}}.bar span{{display:block;height:100%;border-radius:6px;background:var(--teal)}}
.scroll{{overflow:auto}}table{{width:100%;border-collapse:collapse;text-align:left}}td,th{{padding:16px 12px;border-bottom:1px solid var(--line)}}td:last-child{{white-space:nowrap}}
li{{margin:10px 0;color:var(--muted)}}code{{overflow-wrap:anywhere;font-size:12px}}footer{{border-top:1px solid var(--line);margin-top:50px;padding-top:20px;color:var(--muted)}}
@media print{{:root{{color-scheme:light}}body{{background:white;color:#12232a}}main{{padding:20px}}article,.notice{{background:#eef5f4}}.lede,small,li,footer{{color:#314c54}}article{{break-inside:avoid}}}}
</style><main><div class="eyebrow">Nocturne / restoration brief</div>
<h1>{e(statuses[result['status']])}</h1><p class="lede">{e(result['title'])}</p>
<p class="notice">{e(label)}. Planning only; this report does not operate lights.</p>
<div class="stats"><div><strong>${result['cost_usd']:,.0f}</strong>Selected package cost</div><div><strong>${result['budget_usd']:,.0f}</strong>Available budget</div><div><strong>{len(result['actions'])}</strong>Source interventions</div></div>
<p>{e(minimum_text)}</p><h2>Protect every place, in every modeled condition</h2>
<p>Bars show artificial zenith sky brightness remaining relative to each baseline. Lower is darker. Natural sky brightness is excluded. These are modeled values, not field measurements.</p>
<div class="grid">{''.join(cards)}</div><h2>A named owner for every change</h2><div class="scroll"><table><thead><tr><th>Source / owner</th><th>Complete intervention</th><th>Cost</th></tr></thead><tbody>{actions}</tbody></table></div>
<h2>What the planner could not use</h2><ul>{exclusions or '<li>No options excluded by the declared eligibility checks.</li>'}</ul>
<h2>Prove the change, then plan again</h2><p>Preregister randomized baseline/dim windows for one consenting source group at a time. Compare a protected receptor with an unaffected control station. Retain failed windows, estimate the effect in linear luminance, and update only the source coefficients supported by those observations.</p>
<h2>Limits of this result</h2><ul>{''.join('<li>'+e(v)+'</li>' for v in result['limits'])}</ul>
<footer>Christopher Woodyard / Vers3Dynamics · Nocturne<br>{e(result['solver'])}: {result['candidate_portfolios']:,} portfolios.<br>Input fingerprint: <code>{e(result['project_sha256'])}</code></footer></main></html>'''
