import itertools
from lib import *
from c1_f import *
rows=[]
D={s:load(s) for s in ["BTCUSDT","ETHUSDT"]}
def ev(name,f,**kw):
    r={"name":name}
    for s,d in D.items():
        st=stats(bt(d,f(d).values,**kw))
        for k,v in st.items(): r[s[:3]+"_"+k]=v
    rows.append(r)
for N,tr in itertools.product([48,96,288,672,1344,2880],[3,6,10,15,25]):
    ev(f"donch N{N} tr{tr}",lambda d:donch_sig(d,N),trail=tr)
def ema_sig(d,f,s):
    x=d.close.ewm(span=f).mean()>d.close.ewm(span=s).mean()
    return x.astype(int)*2-1
for f,s in [(48,192),(96,384),(192,768),(384,1536),(672,2880),(96,2880)]:
    ev(f"emax {f}/{s}",lambda d:ema_sig(d,f,s),opp=True)
df=pd.DataFrame(rows)
pd.set_option("display.width",250); pd.set_option("display.max_rows",500)
print(df.to_string(index=False))
