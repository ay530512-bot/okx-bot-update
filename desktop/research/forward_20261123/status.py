"""Append dated facts and limits without classifying an unobserved KST day."""
import json,sys
from collections import Counter
from pathlib import Path
from datetime import datetime
from cache_day import KST
def main(root):
    sources=json.loads((root/'result/sources.json').read_bytes());day=json.loads((root/'result/daily_state.json').read_bytes())
    events=json.loads((root/'result/event_paths.json').read_bytes());av=json.loads((root/'work/tape_availability.json').read_bytes())
    c=Counter()
    for s in sources.values():c.update(s['pace'])
    compact={}
    for k,v in day['books'].items():
        compact[k]=dict(coverage_for_events=v['complete_events'],matched={n:{'checked':x['checked'],'missing_known_path':x['unverified'],'net_on_checked_events':x['net_same_quantity'],'stressed_net_on_checked_events':x['stress']} for n,x in v['paired_stats'].items()},accounts={n:{y:x.get(y) for y in ('status','closing_nav','closed_trades','reason','day_return_pct')} for n,x in v['accounts'].items()})
    stat=dict(kst_day=day['date_kst'],recorded_kst=datetime.now(KST).isoformat(),end_exclusive='2026-11-23T00:00:00+09:00',source='publicly replayed development data',package={'version':'2.16.0','commit':'149e4fe69ee11e5c491894af1f28bb309b54668f','sha256':'89f32e493579cdfbc69d880a50f04ab27b50daa6ab69ec1f7ea8dceb2cf3d7e7'},raw_candle_inputs='31/31 native with complete confirmed 1m,5m,15m,1H,1m mark and funding history coverage; source manifests under 20261122/cache',archive_presence={f'{d} HTTP {code}':num for (d,code),num in Counter((r['source_date_utc8'],r['http']) for r in av).items()},pace_intervals=c,fast_raw_windows=sum(s['fast_minute_windows'] for s in sources.values()),signals_15m_observed=sum(s['signals_15m'] or 0 for s in sources.values()),paired_events_in_snapshot=len(events),cohorts=compact,prior_full_day_registrations={'first_eligible_kst':'2026-11-23','closed_eligible_dates':0,'current_day':'in progress; no provisional return'},new_registration={'commit':'ed435b117a4ab256576ec94e341f078bbeb2c5bc','first_full_kst':'2026-11-24','closed_eligible_dates':0,'day_band':'[+5%,+10%] after costs','required_consecutive_dates':60},deployment={'promoted':False,'release_channel_modified':False},pc215_shadow='unobserved; separate local PC journal',real_fills=None)
    (root/'result/run.json').write_text(json.dumps(stat,indent=1,allow_nan=False))
if __name__=='__main__':main(Path(sys.argv[1]))
