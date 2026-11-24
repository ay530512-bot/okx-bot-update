"""Fixed mean-reversion room using only completed original 1m bars."""
import math
def evaluate(rows,t,side,price,stop):
    end=t//60000*60000
    bars=[r for r in rows if end-3600000<=int(r[0])<end]
    if [int(r[0]) for r in bars]!=list(range(end-3600000,end,60000)) or any(r[-1]!='1' for r in bars):
        return {'status':'missing'}
    base=sum(float(r[6]) for r in bars)
    if base<=0:return {'status':'missing'}
    vwap=sum(float(r[7]) for r in bars)/base
    cost=.002*price
    risk=side*(price-stop)
    if not (price>0 and risk>0 and math.isfinite(vwap)):return {'status':'missing'}
    distance=side*(vwap-price)
    needed=max(2*cost,risk+cost)
    return dict(status='pass' if distance>=needed else 'wait',vwap=vwap,room=distance,required=needed)
