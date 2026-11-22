"""Causal public-data reference portfolios. Never substitute an incomplete curve for NAV."""
import heapq,math
from decimal import Decimal
from collections import Counter
def simulate(events,arm,source,opening,info,complete,lock=False):
    if not complete or opening is None:
        return dict(status='missing',closing_nav=None,day_return_pct=None,reason='incomplete signal, price or preceding account history')
    cash=opening;live={};due=[];counts=Counter();fills=[];peak=opening;dd=0;locked=False
    marks=next(iter(info.values()))['marks'] if info else {}
    check_at=(min(marks)+60000) if marks else 0;end=max(marks)+60000 if marks else 0
    def settle(ts):
        nonlocal cash
        while due and due[0][0]<=ts:
            _,sym=heapq.heappop(due);p=live.pop(sym)
            cash+=p['net'];fills.append(p)
    def net_liquidation(t):
        nav=cash
        for sym,p in live.items():
            c=info[sym];prior=t//60000*60000-60000
            if prior not in c['marks']:raise ValueError('missing valuation')
            qty=p['units'];s=p['side'];entry=p['entry'];mark=c['marks'][prior][3];exit_px=mark*(1-s*.0005)
            carry=0
            for ft,rate in c['funding']:
                if p['entry_ts']<ft<=t:carry-=s*qty*rate*c['marks'][ft][0]
            nav+=qty*(s*(exit_px-entry)-.0005*(exit_px+entry))+carry
        return nav
    def advance(until):
        nonlocal cash,check_at,locked,peak,dd
        while check_at and check_at<=min(until,end):
            when=check_at;check_at+=60000
            settle(when)
            nav=net_liquidation(when)
            peak=max(peak,nav);dd=max(dd,1-nav/peak)
            if not lock or locked or nav<1.075*opening:continue
            locked=True
            for sym,pos in list(live.items()):
                tape=info[sym]
                r=tape['first_after'](when)
                if r is None:raise ValueError('lock flatten print unavailable')
                t,_,raw=r[:3]
                if pos['exit']<=t:continue
                side=pos['side'];units=pos['units'];ref=pos['raw_entry']
                carry=-units*side*sum(rate*tape['marks'][ft][0] for ft,rate in tape['funding'] if pos['entry_ts']<ft<=t)
                gross=units*side*(raw-ref)
                def amount(slip):
                    drag=units*slip*(ref+raw)
                    fee=units*.0005*(ref*(1+side*slip)+raw*(1-side*slip))
                    return gross-drag-fee+carry,drag,fee
                net,drag,fee=amount(.0005)
                pos.update(exit=t,net=net,gross=gross,fee=fee,slippage=drag,funding=carry,stress=amount(.001)[0],account_lock=True)
            due[:]=[(p['exit'],sym) for sym,p in live.items()];heapq.heapify(due)
    try:
        # Event paths are used only for admission-independent exits. Future outcomes do not enter selection.
        ordered=[];pending={};consumed=set()
        for ix,e in enumerate(events):
            if source and e.get('source')!=source:continue
            ordered.append((e['signal'],1,e['sym'],ix))
            if 'fill_ref' in e:ordered.append((e['fill_ref'][0],0,e['sym'],ix))
        for ts,action,sym,ix in sorted(ordered):
            e=events[ix];advance(ts);settle(ts)
            if action==1:
                if locked:counts['locked']+=1;continue
                if arm=='E':counts['intentional_skip']+=1;continue
                if arm=='C' and e.get('trend_side')==0:counts['trend_wait']+=1;continue
                if e.get('skip') in ('day_deadline','indicator_history','original_risk_admission'):
                    counts[e['skip']]+=1;continue
                if sym in live or sym in pending or len(live)+len(pending)>=3:
                    counts['duplicate_symbol' if sym in live or sym in pending else 'three_slots']+=1;continue
                anchor=(sym,e['side'],e.get('anchor',e['signal']))
                if anchor in consumed:counts['duplicate_first_anchor']+=1;continue
                if 'fill_ref' not in e:raise ValueError('unverified entry boundary')
                equity=net_liquidation(ts)
                pending[sym]=(ix,max(0,(equity-3)/3),max(0,.005*equity));consumed.add(anchor)
                continue
            if sym not in pending or pending[sym][0]!=ix:continue
            del pending[sym]
            if locked:counts['lock_canceled_pending']+=1;continue
            if e.get('skip'):
                if e['skip']=='below_minimum' and cash>150:raise ValueError('larger balance could change reference minimum admission')
                counts[e['skip']]+=1;continue
            p=e.get(arm)
            if not p or 'net' not in p:raise ValueError('unverified exit or decision')
            equity=net_liquidation(ts);peak=max(peak,equity);dd=max(dd,1-equity/peak)
            ct,lot,minq=[info[sym][k] for k in ('ct','lot','minq')]
            ref=e['fill_ref'][2];s=e['side'] if arm in ('A','B') else e['trend_side'] if arm=='C' else -e['side']
            entry=ref*(1+s*.0005);lev=e['leverage'];q0=p['qty_contracts']
            loss_per_contract=ct*(s*(entry-p['first_stop']*(1-s*.0005))+.0005*(entry+p['first_stop']*(1-s*.0005)))
            if loss_per_contract<=0:raise ValueError('invalid risk')
            slot=max(0,(equity-3)/3)
            free=max(0,equity-3-sum(v['margin'] for v in live.values())-sum(p[1] for p in pending.values()))
            risk_room=max(0,.02*equity-sum(v['risk'] for v in live.values())-sum(p[2] for p in pending.values()))
            # Preserve conservative matched-risk sizing (input quantity was lot-floored at 150).
            n=math.floor(min(q0*equity/150,min(free,slot)*lev/(ct*entry),min(.005*equity,risk_room)/loss_per_contract)/lot+1e-10)*lot
            if n<minq:counts['size_or_risk']+=1;continue
            factor=n/q0
            pos=dict(sym=sym,entry_ts=ts,exit=p['exit_time'],side=s,entry=entry,raw_entry=ref,units=n*ct,qty=n,margin=n*ct*entry/lev,risk=n*loss_per_contract,net=factor*p['net'],stress=factor*p['stressed_net_same_quantity'],gross=factor*p['gross'],fee=factor*p['fee'],slippage=factor*p['slippage'],funding=factor*p['funding'])
            live[sym]=pos;heapq.heappush(due,(pos['exit'],sym))
        advance(end);settle(end)
        if live:raise ValueError('unvalued carry at midnight')
    except (KeyError,ValueError) as err:
        return dict(status='missing',reason=str(err),closing_nav=None,day_return_pct=None,partial_verified_exits=len(fills),counts=dict(counts))
    ret=(cash/opening-1)*100
    close_d,open_d=Decimal(str(cash)),Decimal(str(opening))
    band='below' if close_d<open_d*Decimal('1.05') else 'above' if close_d>open_d*Decimal('1.10') else 'inside'
    bysym=Counter()
    for p in fills:bysym[p['sym']]+=p['net']
    return dict(status=band,profit_lock=lock,lock_triggered=locked,opening_nav=opening,closing_nav=cash,day_return_pct=ret,closed_trades=len(fills),counts=dict(counts),fills=fills,zero_trades=not fills,net=cash-opening,largest_winner=max([0]+[p['net'] for p in fills]),best_symbol=max([0]+list(bysym.values())),net_stress_same_contracts=sum(p['stress'] for p in fills),drawdown_sampled_pct=100*dd)
