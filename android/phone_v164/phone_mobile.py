"""Loopback dashboard, optionally reached through private Tailscale HTTPS Serve.

Strategy/engine modules are never patched. Desktop updater is unavailable here.
"""
import types
import time
from functools import lru_cache
from pathlib import Path
from phone_update import PhoneUpdater
from phone_remote import valid_host


def mover_groups(rows):
    return (sorted((r for r in rows if r.get('change', 0) > 0), key=lambda r: -r['change'])[:5],
            sorted((r for r in rows if r.get('change', 0) < 0), key=lambda r: r['change'])[:5])


def mobile_module(source):
    text = (source / 'okx_mobile.py').read_text()
    patches = {
        'from okx_compact_chart import mover_groups': 'from phone_mobile import mover_groups',
        "if received_origin not in (origin,'https://'+service.config['https_host']):":
            'if received_origin != origin:',
        "if received_origin!='https://'+service.config['https_host']:":
            'if received_origin != origin:',
    }
    for old, new in patches.items():
        if text.count(old) != 1:
            raise ValueError('Unsupported mobile source; refusing adaptation')
        text = text.replace(old, new)
    old_route = "'/api/control/update':'update'"
    if text.count(old_route) != 1: raise ValueError("control route mismatch")
    text = text.replace(old_route, old_route+",'/api/control/calculation':'calculation'")
    anchor = "     if path=='/api/control/result':"
    if text.count(anchor) != 1: raise ValueError('diagnostic route mismatch')
    text = text.replace(anchor,
        "     if path=='/api/phone/diagnostic':\n      self.reply(200,service.diagnostic_export())\n"
        "     elif path=='/api/control/result':", 1)
    route = "     elif path=='/api/chart':"
    if text.count(route) != 1: raise ValueError('live chart route mismatch')
    text = text.replace(route,
        "     elif path=='/api/phone/dashboard-live':\n"
        "      service.live_dashboard.serve(self,args.get('part',['home'])[0],args.get('stream')==['1'])\n"
        "     elif path=='/api/phone/chart-live':\n"
        "      service.live_chart.serve(self,args.get('symbol',[''])[0],args.get('frame',['15m'])[0],args.get('stream')==['1'])\n"+route,1)
    anchor = 'with service.lock:data=copy.deepcopy(service.snapshot)'
    if text.count(anchor) != 1: raise ValueError('dashboard snapshot anchor mismatch')
    text = text.replace(anchor,'data=service.live_dashboard.snapshot(full=True) if hasattr(service,"live_dashboard") else copy.deepcopy(service.snapshot)',1)
    cache_line = "     with self.lock:self.chart_cache[(data['symbol'],data['frame'])]=clean(data)"
    if text.count(cache_line) != 1: raise ValueError('chart cache anchor mismatch')
    text = text.replace(cache_line,"     self.accept_chart(clean(data))",1)
    module = types.ModuleType('phone_q2x_mobile')
    exec(compile(text, str(source / 'okx_mobile.py'), 'exec'), module.__dict__)
    module.POSITION_KEYS = (*module.POSITION_KEYS, 'entry_details')
    module.valid_config = lambda c: (
        (c.get('https_host') == '' or valid_host(c.get('https_host'))) and
        bool(module.re.fullmatch('[0-9a-f]{32}', c.get('salt', ''))) and
        bool(module.re.fullmatch('[0-9a-f]{128}', c.get('password_hash', ''))))
    original_asset = module.asset

    @lru_cache(maxsize=3)
    def asset(name):
        data = original_asset(name).decode('utf-8')
        data = data.replace('PC', '폰').replace('집 폰', '이 폰')
        data = data.replace('폰와 프로그램 및 Tailscale 연결을 유지하세요.', 'Termux와 인터넷 연결을 유지하세요.')
        if name == 'index.html':
            data = data.replace('<section id="marketPanel">', '<section id="phoneMovesPanel"><h2>급등 · 급락 알림</h2><p class="muted">확정 15분봉 시가 → 종가 ±10% · 최근 24시간 · 종목별 최신 1건</p><p class="muted">가격 USDT · 시간 KST · 행을 누르면 차트/수동 진입</p><p id="phoneMoveStatus" class="muted">수신봉 검사 대기</p><div id="phoneMoveRows"></div></section><section id="marketPanel">', 1)
            notice = ('<aside class="phone-host-notice" aria-labelledby="phoneNoticeTitle">'
                '<h2 id="phoneNoticeTitle">OKX Ai trade - 1.6.4</h2>'
                '<p class="phone-host-allocation">공용 3자리 · 추세 5배 전용 1자리 · 시간 KST</p>'
                '<div class="phone-host-rule"><strong>눌림목</strong>'
                '<span class="phone-host-time">롱·숏 24h</span><p>추세·이평선 재확인</p></div>'
                '<div class="phone-host-rule"><strong>확정반전</strong>'
                '<span class="phone-host-time">롱·숏 24h</span><p>확장봉 뒤 반전 마감</p></div>'
                '<div class="phone-host-rule"><strong>두꼬리</strong>'
                '<span class="phone-host-time">롱·숏 24h</span><p>연속 꼬리·고저점 확인</p></div>'
                '<div class="phone-host-rule" title="15:00~다음 02:00 미만">'
                '<strong>추세 롱</strong><span class="phone-host-time">15~다음 02시</span><p>1위 돌파 후 눌림</p></div>'
                '<div class="phone-host-rule" title="05:00~08:00 미만">'
                '<strong>오전 숏</strong><span class="phone-host-time">05~08시</span><p>1위 반등 실패</p></div></aside>')
            data = data.replace('<main>', '<main>'+notice, 1)
            data = data.replace('/style.css?v=732q2x', '/style.css?v=phone164')
            data = data.replace('/app.js?v=732q2x', '/app.js?v=phone164')
            anchor = '<select id="frame"'
            if data.count(anchor) != 1: raise ValueError('chart navigation anchor mismatch')
            data = data.replace(anchor, '<button id="phoneChartNow" type="button" disabled>현재 봉</button>'+anchor, 1)
            data = data.replace('보유·미체결·조건주문이 있으면 설치 보류 · 자동 청산하지 않습니다.',
                '신규 진입 자동 일시정지 · 보유분/거래소 손절 인계 후 기존 운용 복구 · 처리 중인 주문은 인계 보류')
        if name == 'style.css':
            data += '\n' + Path(__file__).with_name('phone_sections.css').read_text()
        if name == 'app.js':
            anchor = '||age>30;'
            if data.count(anchor)!=1: raise ValueError('account display gate anchor mismatch')
            data = data.replace(anchor,'||age>30||d.account_live?.connected===false;',1)
            start = data.index("$('positions').replaceChildren();for(let p of positions){")
            end = data.index("if(!positions.length)$('positions').append(node('p','보유 포지션이 없습니다.','muted'));", start)
            end += len("if(!positions.length)$('positions').append(node('p','보유 포지션이 없습니다.','muted'));")
            data = data[:start] + 'phoneRenderPositions(d,positions,tradeBusy,old);' + data[end:]
            anchor="$('historyRows').append(e)"
            if data.count(anchor)!=1: raise ValueError('History UI anchor mismatch')
            data=data.replace(anchor,"phoneHistoryDetails(e,p);"+anchor,1)
            data += '\n' + Path(__file__).with_name('phone_exit_ui.js').read_text()
            data += '\n' + Path(__file__).with_name('phone_update_ui.js').read_text()
            data += '\n' + Path(__file__).with_name('phone_market_ui.js').read_text()
            data += '\n' + Path(__file__).with_name('phone_position_ui.js').read_text()
            canvas = 'canvas.width=w*ratio;canvas.height=h*ratio;ctx.scale(ratio,ratio);'
            if data.count(canvas) != 1: raise ValueError('chart canvas anchor mismatch')
            data = data.replace(canvas,'const pw=Math.round(w*ratio),ph=Math.round(h*ratio);if(canvas.width!==pw||canvas.height!==ph){canvas.width=pw;canvas.height=ph}ctx.setTransform(ratio,0,0,ratio,0,0);ctx.lineWidth=1;ctx.setLineDash([]);ctx.textAlign="left";')
            anchor = 'let end=state.end===null?data.length:'
            if data.count(anchor) != 1: raise ValueError('chart price anchor mismatch')
            data = data.replace(anchor,'p={...p,chart_last:phoneChartFollowing()?phoneChartPrice():null};'+anchor,1)
            data = data.replace("['entry','stop','partial_price']","['entry','stop','partial_price','chart_last']",1)
            anchor = 'chartGeometry={bars,n,x,y,right,top,bottom,volBottom};paintCandleTip(ctx,w,h);'
            if data.count(anchor) != 1: raise ValueError('chart marker anchor mismatch')
            data = data.replace(anchor,'chartGeometry={bars,n,x,y,right,top,bottom,volBottom};phoneChartMarker(ctx,w,h);paintCandleTip(ctx,w,h);',1)
            data += '\n' + Path(__file__).with_name('phone_chart_ui.js').read_text()
            data += '\n' + Path(__file__).with_name('phone_dashboard_ui.js').read_text()

        if name == 'index.html':
            import re
            data = re.sub(r'<title>.*?</title>', '<title>OKX · 1.6.4</title>', data)
            data = re.sub(r'(<p id="mobileBuild"[^>]*>).*?(</p>)', r'\g<1>버전 1.6.4 · 15분봉 · KST 09시 기준\g<2>', data)
        if name == 'app.js':
            data += '\nconst versionRender112 = render; render = function(d){versionRender112(d); $("mobileBuild").textContent="버전 1.6.4 · 15분봉 · KST 09시 기준";};\n'
        if name == 'style.css':
            data += '\n#part-settings #programUpdate{margin-top:32px;}\n'
        return data.encode('utf-8')
    module.asset = asset

    class PhoneMobile(module.Mobile):
        def __init__(self, *args, **kwargs):
            if len(args)<4 and 'feed_factory' not in kwargs:
                from phone_chart_feed import factory
                kwargs['feed_factory'] = factory(source)
            super().__init__(*args, **kwargs)
            self.calculation_root = Path(args[0]).parent
            self._view_revision = None
            self.capture_rebuilds = 0
            self.capture_reuses = 0
            self.updater = PhoneUpdater(Path(args[0]).parent, self)
            self.hosts = {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}
            self.set_remote(self.config.get('https_host', ''))

        def accept_chart(self, data):
            from phone_chart_live import accept
            accept(self, data)

        def stop(self):
            super().stop()
            if hasattr(self, 'live_chart'): self.live_chart.close()

        def history(self, day, source):
            from phone_exit_details import enrich
            data = super().history(day, source)
            try: return module.clean(enrich(self.root, data), self.hidden)
            except Exception: return data

        def diagnostic_export(self):
            from phone_diagnostic_export import export
            with self.lock:
                summary = dict(getattr(getattr(self, 'performance', None), 'summary_cache', {}))
            data = export(self.calculation_root, summary)
            chart = getattr(self, 'live_chart', None)
            if chart and chart.quotes:
                data['chart_display'] = chart.quotes.diagnostic(chart.clock())
            return module.clean(data, self.hidden)

        def set_remote(self, host):
            if host and not valid_host(host):
                raise ValueError('허용되지 않은 원격 주소')
            with self.lock:
                self.config['https_host'] = host
                self.hosts = {f'127.0.0.1:{self.port}', f'localhost:{self.port}'}
                if host:
                    self.hosts.add(host)

        def enqueue_control(self, op, *args, **kwargs):
            if op == 'calculation':
                if not self.config.get('controls_enabled', False) or self.updater.installing:
                    raise ValueError('계산 방식 변경 대기')
                choice = kwargs.get('key')
                if choice not in ('serial', 'parallel4'):
                    raise ValueError('계산 방식 오류')
                owner, client_id = args[:2]
                if not module.re.fullmatch(r'[A-Za-z0-9_-]{12,80}', client_id): raise ValueError('request id')
                request_id = module.hashlib.sha256((owner+':'+client_id).encode()).hexdigest()[:32]
                from phone_parallel import set_preference
                with self.lock:
                    if request_id in self.control_results: return dict(self.control_results[request_id]['public'])
                    now = time.monotonic()
                    self.control_results = {k:v for k,v in self.control_results.items() if now-v['at']<600}
                    if len(self.control_results)>=128: raise ValueError('requests')
                    set_preference(self.calculation_root, 0 if choice == 'serial' else 4)
                    public = dict(request_id=request_id, status='done', message=('모바일 단일 계산 전환 요청' if choice == 'serial' else '4개 분산 요청')+' · 다음 신호 검사부터 반영')
                    self.control_results[request_id] = dict(owner=owner, at=now, public=public)
                    return public
            if op not in {'update', 'prepare', 'confirm', 'pause', 'entry', 'close_one', 'close_all'}:
                raise ValueError('폰에서는 PC 업데이트를 실행할 수 없습니다.')
            if not self.config.get('controls_enabled', False):
                raise ValueError('조회 모드입니다. PC 종료 후 Termux에서 전환하세요.')
            if self.updater.installing and op in {'prepare', 'confirm', 'entry'}:
                raise ValueError('업데이트 설치 중입니다. 신규 진입을 시작하지 마세요.')
            return super().enqueue_control(op, *args, **kwargs)

        def capture(self, view):
            self.update_state = self.updater.snapshot()
            revision = getattr(view, 'revision', None)
            if revision is None or revision != self._view_revision or not self.snapshot:
                super().capture(view)
                self._view_revision = revision
                self.capture_rebuilds += 1
            else:
                # Reuse presentation arrays only until the next incoming event.
                # Refresh age and controls every loop; never cache market reads.
                with self.lock:
                    self.snapshot['captured_ms'] = int(time.time()*1000)
                    self.snapshot['account_age_seconds'] = max(0,time.monotonic()-view.data_seen) if view.data_seen else None
                    self.snapshot['program_update'] = module.clean(self.update_state,self.hidden)
                    self.snapshot['controls_enabled'] = self.config.get('controls_enabled',True)
                self.capture_reuses += 1
            # Ranking can wait on the whole-market worker. Never hold the HTTP
            # display lock while it runs, or delay chart/private-account deltas.
            payload = None
            if hasattr(self, 'live_market'):
                read = getattr(self.live_market, 'cached', self.live_market.payload)
                payload = read()
            if payload is not None:
                stamp = (payload.get('observed_ms'),payload.get('stale'))
                if getattr(self,'_futures_rows',None) is not payload.get('rows') or getattr(self,'_futures_stamp',None)!=stamp:
                    self._futures_clean = module.clean(payload,self.hidden)
                    self._futures_rows,self._futures_stamp = payload.get('rows'),stamp
            with self.lock:
                self.display_basis = module.clean(view.state.get('display_basis') or {})
                self.snapshot['phone_host'] = True
                if payload is not None:
                    self.snapshot['futures'] = self._futures_clean
                if hasattr(self, 'market_alerts'):
                    self.snapshot['market_alerts'] = self.market_alerts.snapshot()
                self.snapshot['display_work'] = dict(rebuilds=self.capture_rebuilds,reuses=self.capture_reuses)
                if hasattr(self, 'performance'):
                    self.snapshot['performance'] = dict(self.performance.summary_cache)
                self.snapshot['external_access'] = bool(self.config.get('https_host'))

    module.PhoneMobile = PhoneMobile
    return module
