"""Account replay for the PC 2.6 scheduled entries. Fee and slippage are 5 bps each per side."""
from collections import Counter,defaultdict
import json,math,os,sys
from pathlib import Path
import pandas as pd
p=Path(os.environ.get('PC_PACKAGE','OKX_PC_PACKAGE')).resolve()
sys.path[:0]=[str(p/'runtime'),str(p/'core')]
from pc_forward import qualifies
import pc_scalp
import pc_timing

def audit(path,instruments):
    df=pd.read_pickle(path).sort_values(['entry','rule','rv','symbol'],ascending=[True,True,False,True])
    universe={x['instId'].split('-')[0]:x for x in instruments['data']}
    rows=df.drop_duplicates(['entry','rule']).copy()
    rows['scalp']=rows.rule.isin(pc_scalp.SPECS)
    rows['common']=~rows.rule.isin({'rank_short','trend_long'})
    rows=rows.sort_values(['entry','scalp','common','rv','symbol'],ascending=[True,True,True,False,True])
    def run(observe):
        hist=defaultdict(list); shadow={};daily=Counter();positions={};ledger=[];closed=Counter();cash=peak=150.;dd=0.
        def settle(now):
            nonlocal cash,peak,dd
            for key, (end,symbol,margin,loss,pnl) in sorted(list(positions.items()),key=lambda kv:kv[1][0]):
                if end<=now:
                    cash+=pnl;peak=max(peak,cash);dd=max(dd,100*(1-cash/peak));ledger.append(pnl);del positions[key]
            for key, (known,entry,exit,net_r) in list(shadow.items()):
                if known<=now:
                    hist[key].append(dict(entry_ms=entry,exit_ms=exit,net_r=net_r));closed[key]+=1
                    del shadow[key]
        for r in rows.itertuples():
            t=int(r.entry);settle(t)
            if not math.isfinite(r.net) or r.exit>END:continue
            key=r.rule;day=(t+(9*3600000 if r.scalp else 0))//86400000
            if key in shadow or daily[(day,key)] >= (pc_scalp.SPECS[key][-1] if r.scalp else 1):continue
            distance=abs(r.price-r.stop)/r.price+.002
            permitted=qualifies(hist[key],t)
            # The on-PC watcher settles after the observation deadline using public mark and trade data.
            shadow[key]=(t+(r.hold+1)*60000,t,int(r.exit),r.net/distance);daily[(day,key)]+=1
            if observe and not permitted:continue
            if len(positions)>=3 or key in positions or any(x[1]==r.symbol for x in positions.values()):continue
            equity=max(0,cash-3);target=equity/3
            i=universe[r.symbol];ct=float(i['ctVal']);lot=float(i['lotSz'])
            qty=math.floor(target/(ct*r.price*(1/r.leverage+.0005))/lot)*lot
            if qty<float(i['minSz']) or qty>float(i['maxMktSz']):continue
            nominal=qty*ct*r.price;margin=nominal/r.leverage;loss=nominal*distance;outlay=margin+nominal*.0005
            if margin<.97*target or outlay+sum(p[2] for p in positions.values())>equity or loss>min(.005*equity,.02*equity-sum(p[3] for p in positions.values())):continue
            positions[key]=(r.exit,r.symbol,outlay,loss,nominal*r.net)
        settle(END)
        return dict(initial_usdt=150,final_usdt=round(cash,4),net_pct=round((cash/150-1)*100,3),trades=len(ledger),max_closed_drawdown_pct=round(dd,3),observations=dict(closed))
    return dict(start_kst='2026-09-22',end_exclusive_kst='2026-11-21',symbols=len(pc_scalp.SYMBOLS),
                candle_model='1m public traded OHLC; next open, funding; no archived order book or mark trigger replay; empty observation history',
                fresh_gate=run(True),signals_without_qualification=run(False))
END=int(pd.Timestamp('2026-11-21',tz='Asia/Seoul').timestamp()*1000)
if __name__=='__main__':
    report=audit('market_cache/opportunities.pkl',json.loads(Path(sys.argv[1]).read_text()))
    print(json.dumps(report,ensure_ascii=False,indent=2))
