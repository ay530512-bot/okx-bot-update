import sys,datetime
sys.path.insert(0,'chart_update')
from okx_position_chart import STEPS,parse,API_FRAMES
from okx_pattern15 import STEPS as strategy_steps
assert set(strategy_steps)=={'15m','1H','4H'}
for frame,stamp in [('1m','2026-11-12T00:01:00'),('1D','2026-11-12T00:00:00'),('1W','2026-11-09T00:00:00')]:
 t=int(datetime.datetime.fromisoformat(stamp).replace(tzinfo=datetime.timezone.utc).timestamp()*1000)
 row=[str(t),'1','2','.5','1.5','100','200','300','1']
 assert len(parse([row],frame,t+STEPS[frame]))==1
 row[0]=str(t+1000)
 assert parse([row],frame,t+STEPS[frame])==[]
assert API_FRAMES=={'1D':'1Dutc','1W':'1Wutc'}
print('PASS 1m/day/week timestamp alignment, UTC API mapping; strategy frames unchanged')
