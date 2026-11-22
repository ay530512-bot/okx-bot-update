"""Record paired differences and counterexamples; thresholds unchanged for the holdout."""
import json,sys
from pathlib import Path
from statistics import mean
def make(root):
    a=json.loads((root/'result/event_paths.json').read_bytes())
    matched=[r for r in a if 'net' in r.get('A',{}) and 'net' in r.get('B',{})]
    delta=[r['A']['net']-r['B']['net'] for r in matched]
    p=[r for r in a if 'net' in r.get('B',{}) and 'net' in r.get('D',{})]
    gates={}
    for k in ('aligned_and_breadth','absorption_then_turn'):
        groups={}
        for code,val in [('pass',True),('fail',False),('unverified',None)]:
            bucket=[r for r in matched if r.get('pre_flow',{}).get(k) is val]
            groups[code]=dict(n=len(bucket),A_sum_net=sum(r['A']['net'] for r in bucket),B_sum_net=sum(r['B']['net'] for r in bucket))
        gates[k]=groups
    notes=dict(calendar_role='2026-11-22 KST: already inspected development day',first_complete_eligible_for_current_registration='2026-11-24',matched_AB_n=len(delta),A_minus_B_total=sum(delta),A_minus_B_mean=mean(delta) if delta else None,A_improves=sum(x>1e-9 for x in delta),A_worsens=sum(x< -1e-9 for x in delta),B_D_comparable=len(p),loss_both_sides=sum(max(r['B']['net'],r['D']['net'])<0 for r in p),positive_gross_but_negative_after_costs_B=sum(r['B']['gross']>0 and r['B']['net']<0 for r in matched),same_quantity_cost_gate_diagnostics=gates,inference='These are conditional differences on identical checked opportunity paths. They do not establish an indicator cause, prove a live fill or qualify a rule on independent dates.',next_test='Apply the already frozen same-direction-share and peer-breadth gates to new prints, including the opposite-pressure/then-turn variant, holding entry, risk cap, and realized exit method fixed. Compare coverage and frequency of wins as well as costs, separately for fast and normal pace. Examine sample loss explicitly; no new threshold was selected from the day.')
    (root/'result/assessment.json').write_text(json.dumps(notes,indent=1))
if __name__=='__main__':make(Path(sys.argv[1]))
