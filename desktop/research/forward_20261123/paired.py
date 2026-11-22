"""Research-only matched event paths. Fixed 150-USDT reference, no account-equity inference."""
import gzip,json,math,sys
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache
from pathlib import Path
from bisect import bisect_right
from cache_day import api
from direct_ticks import minute,M,F
def run(sym,cache,tape,results,package):
    sys.path.insert(0,str(package/'runtime'))
    from pc_symbol_flow import assess_market
    from scan import native_pace
    from pc_sizing import indicators,leverage_for,round_stop,ema
    data=json.load(gzip.open(cache/(sym+'.json.gz')))
    frames={k:[(int(r[0]),*map(float,r[1:6])) for r in data[k]] for k in ['1m','5m','15m','1H']}
    times={k:[r[0] for r in v] for k,v in frames.items()}
    raw={int(r[0]):r for r in data['1m']}; mark={int(r[0]):list(map(float,r[1:5])) for r in data['mark1m']}
    deadline=max(mark);inst=data['instrument'][0];tick=float(inst['tickSz']);ct=float(inst['ctVal']);lot=float(inst['lotSz']);minq=float(inst['minSz'])
    def hist(k,ts,step,n=160):
        i=bisect_right(times[k],ts-step);return frames[k][max(0,i-n):i]
    def trend(ts):
        q=[r[4] for r in hist('15m',ts,15*M)];h=[r[4] for r in hist('1H',ts,60*M)]
        if len(q)<20 or len(h)<21:return 0
        d=(ema(q,9)-ema(q,20),h[-1]-ema(h,20),ema(h,20)-ema(h[:-1],20))
        return int(min(d)>0)-int(max(d)<0)
    @lru_cache(None)
    def seconds(m):
        key=tape/('mark-'+sym+'-'+str(m)+'.json.gz')
        if key.exists():a=json.load(gzip.open(key))
        else:
            a=api('market/history-mark-price-candles',instId=sym+'-USDT-SWAP',bar='1s',after=m+M,limit=60)
            a=[r for r in a if r[-1]=='1' and m<=int(r[0])<m+M]
            if sorted(int(r[0]) for r in a)!=list(range(m,m+M,1000)):raise ValueError('incomplete mark seconds')
            key.write_bytes(gzip.compress(json.dumps(a,separators=(',',':')).encode(),mtime=0))
        return sorted([(int(r[0]),*map(float,r[1:5])) for r in a])
    @lru_cache(None)
    def next_print(ts):
        m=ts//M*M
        if (tape/(sym+'-'+str(m)+'.json.gz')).exists():
            for r in minute(sym,m,raw,tape):
                if r[0]>=ts:return r
        key=tape/('boundary-'+sym+'-'+str(ts)+'.json.gz')
        if key.exists():return json.load(gzip.open(key))['next']
        contract=sym+'-USDT-SWAP'
        prev=api('market/history-trades',instId=contract,type=2,after=ts,limit=1)[0]
        before=int(prev['tradeId'])
        nxt=api('market/history-trades',instId=contract,type=1,after=before+2,limit=1)[0]
        found=[int(nxt['ts']),int(nxt['tradeId']),float(nxt['px']),float(nxt['sz']),nxt['side']]
        if int(prev['ts'])>=ts or found[0]<ts or found[1]!=before+1 or found[0]>=deadline+M:
            raise ValueError('unverified boundary trade')
        key.write_bytes(gzip.compress(json.dumps(dict(previous=prev,next=found)).encode(),mtime=0))
        return found
    def path(ts,ref,s,stop,tp,qty):
        entry=ref*(1+s*.0005);risk=s*(entry-stop);active=stop
        if risk<=0:raise ValueError('invalid structural distance')
        why='day';when=deadline
        def adverse(lo,hi):
            return lo<=active+tick*1e-7 if s==1 else hi>=active-tick*1e-7
        def target(lo,hi):
            return tp is not None and (hi>=tp if s==1 else lo<=tp)
        def trail(px):
            if tp is not None or s*(px-entry)<risk:return active
            v=round_stop(px-s*risk,tick,s);return max(v,active) if s==1 else min(v,active)
        for m in range(ts//M*M,deadline,M):
            _,hi,lo,_=mark[m]
            if not adverse(lo,hi) and not target(lo,hi) and trail(hi if s==1 else lo)==active:continue
            for t,o,hi,lo,c in seconds(m):
                if t+1000<=ts:continue
                if t<ts and (adverse(lo,hi) or target(lo,hi) or trail(hi if s==1 else lo)!=active):
                    raise ValueError('entry-second order ambiguous')
                a=adverse(lo,hi);b=target(lo,hi)
                if a and b:raise ValueError('both exits in one mark second')
                if a or b:
                    why='target' if b else 'initial' if active==stop else 'trail';when=t+1000;break
                active=trail(c)  # mark-based trailing evaluated on completed one-second updates
            else:continue
            break
        et,tid,x,*_=next_print(when)
        carry=0.
        for row in data['funding']:
            ft=int(row['fundingTime'])
            if ts<ft<=et:
                if not row.get('realizedRate'):raise ValueError('unresolved funding')
                carry-=s*float(row['realizedRate'])*mark[ft][0]*qty*ct
        gross=qty*ct*s*(x-ref)
        def costs(slip):
            ep=ref*(1+s*slip);xp=x*(1-s*slip)
            fee=qty*ct*.0005*(ep+xp);drag=qty*ct*slip*(ref+x)
            return dict(fee=fee,slippage=drag,net=gross-fee-drag+carry)
        return dict(exit_time=et,exit_trade_id=tid,exit_raw=x,reason=why,first_stop=stop,qty_contracts=qty,gross=gross,funding=carry,**costs(.0005),stressed_net_same_quantity=costs(.001)['net'])
    out=[]
    for r in results:
        if r.get('status')!='reaction':continue
        if 'fill_ref' not in r:
            try:r=dict(r,fill_ref=next_print(r['ts']+1)[:3])
            except (ValueError,KeyError,OSError) as exc:
                out.append(dict(sym=sym,signal=r['ts'],side=r['side'],unverified=str(exc)));continue
        ts,_,ref=r['fill_ref'];s=r['side'];res=dict(sym=sym,source=r.get('source','native_fast_direct'),signal=r['ts'],side=s,fill_ref=r['fill_ref'],anchor=r['anchor'],first=r['first'],second=r['second'],no_entry_net=0)
        out.append(res)
        t=r['ts'];i=bisect_right(times['5m'],t-F)
        speed=native_pace(data['5m'][max(0,i-40):i],t//F*F)
        dec=assess_market(hist('15m',t,15*M,260),hist('5m',t,F,260),hist('1H',t,60*M),t,s,hist('1m',t,M))
        res.update(native_pace=speed,release_pace=dec['pace'],release_selected_side=dec['side'],release_decision_reason=dec['reason'],prior_anchor_state=r.get('prior_anchor_state','known'))
        res['closed_minute_diagnostics']={}
        for n in (5,15,30):
            mt=(ts+n*M)//M*M-M
            if mt not in raw or mt+M>ts+n*M:continue
            res['closed_minute_diagnostics'][n]=dict(close_ms=mt+M,close=float(raw[mt][4]),signed_move=s*(float(raw[mt][4])/ref-1))
        if ts>=deadline:res['skip']='day_deadline';continue
        frame='15m' if r.get('source')=='deployed_wick15' else '5m'
        bars=hist(frame,r['ts'],15*M if frame=='15m' else F);ev=indicators(bars,s,r['atr'])
        if ev is None:res['skip']='indicator_history';continue
        stop=round_stop(r['first']-s*max(2*tick,.15*r['atr']),tick,s)
        ev['stop']=stop;lev=leverage_for(ev,r['price'],float(inst['lever']))
        res.update(pre=ev,trend_side=trend(r['ts']),leverage=lev)
        if lev<3:res['skip']='original_risk_admission';continue
        entry=ref*(1+s*.0005);diff=s*(entry-stop)
        if diff<=0:res['skip']='crossed_structural_stop';continue
        pos={}
        for name,side in [('A',s),('B',s),('C',res['trend_side']),('D',-s)]:
            if not side:continue
            e=ref*(1+side*.0005)
            fixed=name in ('A','C')
            level=round_stop(e*(1-side*.01),tick,side) if fixed else stop if name=='B' else round_stop(e-side*diff,tick,side)
            tp=round_stop(e*(1+side*.01),tick,-side) if fixed else None
            raw_loss=side*(ref-level)+.0005*(ref+level)+.0005*(e+level*(1-side*.0005))
            pos[name]=(side,level,tp,raw_loss*ct)
        permitted=(150-3)/3*lev/(entry*ct)
        budget=min(.75,permitted*pos['B'][3])
        q=math.floor(min(permitted,*[budget/x[3] for x in pos.values()])/lot)*lot
        res.update(qty_contracts=q,risk_budget_usdt=budget,entry_margin=q*ct*entry/lev,sizing='minimum shared across active arms and original slot')
        if q<minq:res['skip']='below_minimum';continue
        for name,(side,level,tp,loss) in pos.items():
            try:res[name]=path(ts,ref,side,level,tp,q)
            except (ValueError,KeyError,OSError,RuntimeError) as err:res[name]={'unverified':str(err)}
        res['markouts']={}
        for n in (5,15,30):
            if ts+n*M>=deadline+M:continue
            try:
                t,i,p,*_=next_print(ts+n*M)
                res['markouts'][n]=dict(time=t,trade_id=i,price=p,signed_move=s*(p/ref-1)) if t<=ts+n*M+15000 else dict(missing='stale trade')
            except (ValueError,KeyError,OSError,RuntimeError) as err:res['markouts'][n]={'unverified':str(err)}
    return out
if __name__=='__main__':
    cache,tape,direct,out,package=map(Path,sys.argv[1:])
    out.mkdir(exist_ok=True)
    def work(p):
        dest=out/p.name
        if not dest.exists():dest.write_text(json.dumps(run(p.stem,cache,tape,json.loads(p.read_bytes()),package),separators=(',',':')))
    with ThreadPoolExecutor(12) as pool:list(pool.map(work,sorted(direct.glob('*.json'))))
