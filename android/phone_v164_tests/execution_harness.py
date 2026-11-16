"""Production entry code, fake exchange at the I/O boundary. No real order API."""
import copy,json,queue,socket,sys,tempfile,time,threading
from pathlib import Path
from types import SimpleNamespace as NS
D=Path(__file__).resolve().parent;W=D.parents[2];HOST=D.parent/'phone_v164';CORE=W/'core121'
sys.path[:0]=[str(HOST),str(CORE)]
from okx_core import BotError,Rejected,UnknownOutcome,dec,fmt
from okx_v5 import RuleEngine
import okx_channel701 as channel
import phone_trend_slot as trend
from phone_parallel import set_preference
from phone_mobile_compute import Manager
from phone_quote_registry import attach as attach_quotes

NETWORK_ATTEMPTS=[]
def no_connect(sock,address):
 NETWORK_ATTEMPTS.append(str(address));raise AssertionError('offline fixture attempted a network connection')
# No external network even if an unexpected production code path is reached.
socket.socket.connect=no_connect
socket.socket.connect_ex=no_connect
socket.create_connection=lambda *a,**k:(_ for _ in ()).throw(AssertionError('network disabled'))

def configured():
 """Validated fixture configuration, not a claim about the user's saved config."""
 from okx_pattern15 import configure,validate_config
 cfg=dict(indicators=dict(bb_period=20,bb_multiplier=2,ma_type='SMA',ma_periods=[15,20,50,100,120,200]),
  risk=dict(profit_review_roe=.20,final_stop_roe=-.30,daily_stop=-.21,daily_cap=10,stop_slippage_buffer=.001,liquidation_buffer=.01),
  signals=dict(band_flow={}),selection={},liquidity=dict(ws_max_age_seconds=15,trade_max_age_seconds=60,max_book_age_ms=2000),
  notifications=dict(enabled=False,repeat_wait_seconds=60),
  execution=dict(free_ai={},autonomous_scalp={},budget_pacing={},manual_coexist=True,whole_market=True,continuous_trading=True,recovery_snapshots=3,chart_refresh_seconds=10))
 configure(cfg);cfg['risk']['profit_review_roe']=.20;validate_config(cfg)
 return cfg

BOOT=None
def bootstrap():
 global BOOT
 if BOOT:return BOOT
 from phone_pullback_size import install as size_install
 from phone_public_ws import install as ws_install
 from phone_performance import install_before_engine
 from phone_exit_details import install as exit_install
 from phone_entry_feed import install as feed_install
 size_install(CORE);ws_install();__import__('phone_public_lanes').install()
 BOOT=install_before_engine(D)
 trend.install(CORE);exit_install(CORE);feed_install()
 return BOOT

def instrument(symbol):
 return dict(instId=symbol,state='live',settleCcy='USDT',ctType='linear',ctValCcy=symbol.split('-')[0],
  instCategory='1',lever='100',tickSz='.000001',lotSz='.01',minSz='.01',ctVal='1',maxMktSz='10000000')

class FakeExchange:
 """Strict, auditable transport. ACK and fills are separate observations."""
 def __init__(self):
  self.now=0;self.rows={};self.rank_bases={};self.live_prices={};self.positions=[];self.orders={};self.algos=[];self.calls=[];self.levers={}
  self.unknown=False;self.reject=False;self.spread=dec('.0002');self.engine=None
  self.available=dec(300);self.equity=dec(300);self.changed=False;self.stop_touch=False
 def now_ms(self):return self.now
 def quote(self,symbol):
  p=dec(self.live_prices.get(symbol,self.rows[symbol]['live_frames']['15m'][-1][4]));half=self.spread/2
  from decimal import ROUND_DOWN,ROUND_UP
  tick=dec(instrument(symbol)['tickSz'])
  bid=(p*(1-half)/tick).to_integral_value(rounding=ROUND_DOWN)*tick
  ask=(p*(1+half)/tick).to_integral_value(rounding=ROUND_UP)*tick
  return dict(instId=symbol,ts=str(self.now),last=fmt(p),bidPx=fmt(bid),askPx=fmt(ask),sodUtc0=str(self.rank_bases.get(symbol) or self.rows[symbol].get('rank_base') or next((b[1] for b in self.rows[symbol]['live_frames']['1H'] if b[0]==self.now//86400000*86400000),float(p))))
 def book(self,symbol):
  q=self.quote(symbol)
  return dict(ts=q['ts'],bids=[[q['bidPx'],'1000000','0','1']],asks=[[q['askPx'],'1000000','0','1']])
 def snapshot(self):
  self.calls.append(('snapshot',{}))
  used=sum((dec(p['margin']) for p in self.positions),dec(0))
  return dict(ms=self.now,config=dict(acctLv='2',posMode='long_short_mode',uid='OFFLINE-ONLY',perm='read_only,trade'),
   equity=self.equity,available=self.available-used,positions=copy.deepcopy(self.positions),
   orders=[copy.deepcopy(o) for o in self.orders.values() if o['state'] in ('live','partially_filled')])
 def taker_fee(self,i):return dec('.0005')
 def pending_algos(self,full=False):self.calls.append(('pending_algos',{'full':full}));return copy.deepcopy(self.algos)
 def public(self,path,**kw):
  self.calls.append(('public '+path,kw));s=kw.get('instId')
  if path=='/api/v5/public/instruments':return [instrument(s)]
  if path=='/api/v5/market/ticker':return [self.quote(s)]
  if path=='/api/v5/market/books':return [self.book(s)]
  if path=='/api/v5/market/candles':
   step={'15m':900000,'1H':3600000,'4H':14400000}[kw['bar']]
   b=copy.deepcopy(self.rows[s]['live_frames'][kw['bar']])
   if self.changed and kw['bar']=='15m':b[-1][4]=b[-1][3]
   if self.stop_touch and kw['bar']=='15m':
    p=b[-1][4];b.append([self.now//step*step,p,p*1.2,p*.8,p,0])
   return [[str(int(r[0]))]+[str(v) for v in r[1:6]]+['0','0','1' if r[0]+step<=self.now else '0'] for r in b[-int(kw.get('limit',300)):]][::-1]
  raise AssertionError(('unmodelled public endpoint',path,kw))
 def get(self,path,**kw):
  self.calls.append(('get '+path,kw))
  if path=='/api/v5/account/bills':return []
  if path=='/api/v5/account/max-size':return [dict(maxBuy='10000000',maxSell='10000000')]
  if path=='/api/v5/account/leverage-info':
   return [dict(instId=s,posSide=d,mgnMode='isolated',lever=l) for (s,d),l in self.levers.items() if s==kw['instId']]
  if path=='/api/v5/trade/order':
   if kw['clOrdId'] not in self.orders:raise Rejected('offline unknown client ID')
   return [copy.deepcopy(self.orders[kw['clOrdId']])]
  raise AssertionError(('unmodelled private read',path,kw))
 def post(self,path,body):
  self.calls.append(('post '+path,copy.deepcopy(body)))
  if path=='/api/v5/account/set-leverage':
   self.levers[(body['instId'],body['posSide'])]=body['lever'];return [dict(lever=body['lever'])]
  if path=='/api/v5/trade/order':
   if self.reject:raise Rejected('offline explicit exchange rejection')
   assert body['clOrdId'] not in self.orders,'duplicate client ID write'
   # Verify the durable intention exists BEFORE the exchange sees the opening request.
   if body.get('attachAlgoOrds'):
    disk=json.loads(self.engine.journal.path.read_text())
    assert disk['owned']['client_id']==body['clOrdId'] and disk['owned']['phase']=='submitted'
   self.orders[body['clOrdId']]=dict(body,state='live',accFillSz='0',avgPx='',ordId='fake-'+str(len(self.orders)+1))
   if self.unknown:raise UnknownOutcome('offline response lost after acceptance')
   return [dict(ordId=self.orders[body['clOrdId']]['ordId'],clOrdId=body['clOrdId'],sCode='0')]
  if path=='/api/v5/trade/cancel-order':
   self.orders[body['clOrdId']]['state']='canceled';return [dict(sCode='0')]
  raise AssertionError(('unmodelled write',path,body))
 def fill(self,client_id,protect=True,fraction=1):
  o=self.orders[client_id];s=o['instId'];side=o['posSide'];q=dec(o['sz'])*dec(fraction)
  price=dec(self.quote(s)['askPx' if side=='long' else 'bidPx']);lev=dec(self.levers[(s,side)]);margin=q*price/lev
  o.update(state='filled' if fraction==1 else 'partially_filled',accFillSz=fmt(q),avgPx=fmt(price))
  self.positions.append(dict(instId=s,posSide=side,mgnMode='isolated',pos=fmt(q),lever=fmt(lev),posId='fake-pos-'+client_id,
   avgPx=fmt(price),markPx=fmt(price),liqPx=fmt(price*(dec('.8') if side=='long' else dec('1.2'))),margin=fmt(margin),imr=fmt(margin),notionalUsd=fmt(q*price),upl='0',uplRatio='0'))
  if protect:
   a=o['attachAlgoOrds'][0]
   self.algos.append(dict(instId=s,posSide=side,algoClOrdId=a['attachAlgoClOrdId'],algoId='fake-sl-'+client_id,state='live',sz=fmt(q),ordType='conditional',**{k:a[k] for k in ('slTriggerPx','slTriggerPxType','slOrdPx')}))
 def opening_posts(self):return [v for p,v in self.calls if p=='post /api/v5/trade/order' and v.get('attachAlgoOrds')]

class Harness:
 def __init__(self,fixture,workers=0):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);runtime=self.root/'runtime-q2x';runtime.mkdir()
  self.cfg=configured();(runtime/'strategy_config.json').write_text(json.dumps(self.cfg))
  self.timer=bootstrap();set_preference(self.root,workers)
  self.api=FakeExchange();
  if 'arming_rows' in fixture:
   # Synthetic ticker baseline keeps the historic setup's symbol first.
   # Dedicated live-ranking tests vary prices and leaders independently.
   rank=trend.rank_rows([r for r in fixture['arming_rows'] if any(b[0]==fixture['arming_now']//86400000*86400000 for b in r['live_frames']['1H'])],fixture['arming_now'])
   r=next(r for r in fixture['arming_rows'] if r['symbol']==rank['symbol'])
   self.api.rank_bases[rank['symbol']]=r['live_frames']['15m'][-1][4]*.8
  self.e=RuleEngine(runtime,{'TRADING_EXCHANGE':'okx'},queue.Queue(),exchange=self.api);self.api.engine=self.e
  e=self.e;e.enabled=True;e.recovering=False;e.user_paused=False;e.entry_cancel.clear();e._phone_perf=self.timer;e.connection_key=(1,1)
  e.account_stream.connected=True;e.account_stream.generation=1;e.account_stream.equity=300;e.account_stream.received=time.monotonic()
  e.stream.connected=True;e.stream.generation=1
  pins=json.loads((HOST/'phone_sources.json').read_text());self.manager=Manager(self.root,pins,str(CORE),self.timer);self.timer.parallel=self.manager
  attach_quotes(e)
  self.feed(fixture.get('arming_rows',fixture['rows']),fixture.get('arming_now',fixture['now']))
  e.journal.data['session']=dict(start_ms=self.api.now-1000,end_ms=self.api.now+86400000,continuous=True,ended=False)
  e.journal.roll_day(self.api.now,dec(300),initialize=True);e.journal.save()
  self.fixture=fixture
 def feed(self,rows,now,quotes=True):
  self.api.now=int(now);rs=copy.deepcopy(rows)
  for r in rs:r['instrument']=instrument(r['symbol']);r['observed_ms']=int(now)
  self.api.rows={r['symbol']:r for r in rs}
  e=self.e;u=e.universe
  u.result=dict(rows=rs,whole_market=True,universe=len(rs),ms=now,filter_counts={'data_error':0})
  u.full_market.instruments={r['symbol']:r['instrument'] for r in rs}
  u.full_market.band_cache={(r['symbol'],f):(time.monotonic(),tuple(tuple(b) for b in bs)) for r in rs for f,bs in r['live_frames'].items()}
  u.full_market.quotes={s:self.api.quote(s) for s in self.api.rows};u.full_market.quote_ms=now;u.full_market.quote_error=None
  if hasattr(e,'_phone_live_rank'):e._phone_live_rank.value=None
  e.account_stream.received=time.monotonic()
  for r in rs:
   e.charts[r['symbol']]=(copy.deepcopy(r['live_frames']),time.monotonic());e.next_charts[r['symbol']]=time.monotonic()+10000
  if quotes:self.ready()
 def ready(self):
  s=self.e.stream;s.symbols.update(self.api.rows)
  for symbol in self.api.rows:
   q=self.api.quote(symbol)
   for c in s.CHANNELS:
    row=self.api.book(symbol) if c=='books5' else dict(q,px=q['last'],markPx=q['last'])
    s.data[(symbol,c)]=(row,time.monotonic(),s.generation);s.active_pairs.add((symbol,c))
 def compute(self):
  self.manager.prepare(self.e)
  if self.manager.future:self.manager.future.result(timeout=30)
  self.manager.prepare(self.e)
 def candidate(self):
  self.compute();return self.e.candidate_decision()
 def signal(self):
  if 'arming_rows' in self.fixture:
   self.candidate()
   assert self.e.journal.data[trend.STATE].get('arm'),'actual breakout did not arm'
   self.feed(self.fixture['rows'],self.fixture['now'])
  s=self.candidate()
  assert s is not None,dict(diagnostic=getattr(self.e,'phone_entry_diagnostic',None),trend=getattr(self.e,'phone_trend_status',None))
  return s
 def submit(self,s):
  self.e.executing_signal=s
  with self.e.selected(self.e.empty_slot()):self.e.entry(s)
  return next((r for r in self.e.records() if r['symbol']==s['symbol']),None)
 def reconcile(self,o):
  records=[self.e.journal.data['owned'],self.e.journal.data['extra_owned']]+self.e.journal.data.get('additional_owned',[])
  slot=records.index(o)
  with self.e.selected(slot):
   snap=self.e.snapshot();p=self.e.reconcile(snap)
   return bool(p and self.e.verify_protection(snap,p,o))
 def close(self):
  self.e.stop_event.set();self.manager.close();self.manager.executor.shutdown(wait=True,cancel_futures=True)
  for obj in (self.e.executor,self.e.chart_executor,self.e.chart_pool,self.e.approval_pool,self.e.position_history.pool):obj.shutdown(wait=True,cancel_futures=True)
  self.temp.cleanup()
