import gzip,json,sys
from pathlib import Path
from datetime import datetime,timedelta,timezone
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
def plot(root):
    events=sorted(json.loads((root/'result/event_paths.json').read_bytes()),key=lambda e:e['signal'])
    zone=timezone(timedelta(hours=9))
    for label,positive in [('winner',True),('counterexample',False)]:
        e=next((r for r in events if 'net' in r.get('A',{}) and (r['A']['net']>0)==positive and r['A']['net']!=0),None)
        if e is None:continue
        z=json.load(gzip.open(root/'cache'/(e['sym']+'.json.gz')));a=e['A'];start=e['signal']-3600000;end=a['exit_time']+600000
        tf='5m' if end-start<4*3600000 else '15m';step=300000 if tf=='5m' else 900000
        sel=[(int(r[0]),*map(float,r[1:5])) for r in z[tf] if start<=int(r[0])<=end]
        fig,ax=plt.subplots(figsize=(9,4));ax.grid(axis='y',alpha=.2)
        for t,o,h,l,c in sel:
            color='#00775b' if c>=o else '#b94048';ax.plot([t,t],[l,h],c=color,lw=1);ax.add_patch(Rectangle((t-step*.30,min(o,c)),step*.60,max(abs(o-c),1e-10),color=color))
        for t,p,lab in [(e['fill_ref'][0],e['fill_ref'][2],'Entry'),(a['exit_time'],a['exit_raw'],'Exit')]:
            ax.scatter(t,p,c='#282121',s=26,zorder=4);ax.annotate(lab,(t,p),xytext=(3,8),textcoords='offset points',fontsize=9)
        ax.axhline(a['first_stop'],c='#b94048',ls='--',lw=.8)
        ax.set_title(f"{e['sym']} · {'Long' if e['side']==1 else 'Short'} · {datetime.fromtimestamp(e['signal']/1000,zone):%Y-%m-%d %H:%M:%S} KST · net {a['net']:+.4f} USDT")
        xs=[r[0] for r in sel[::max(1,len(sel)//6)]];ax.set_xticks(xs,[datetime.fromtimestamp(t/1000,zone).strftime('%H:%M') for t in xs]);ax.set_xlabel(f'{tf} public candles · Korea time');ax.set_ylabel('USDT');fig.tight_layout();fig.savefig(root/'result'/f'{label}.png',dpi=135);plt.close(fig)
if __name__=='__main__':plot(Path(sys.argv[1]))
