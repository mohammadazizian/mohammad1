import itertools
from lib import *
from c6 import cme
pd.set_option("display.width",280); pd.set_option("display.max_rows",500)
def shock(d,n=16,z=4):
    sg=np.log(d.close).diff().rolling(96*7).std()
    x=(np.log(d.close)-np.log(d.close.shift(n)))/(sg*np.sqrt(n))
    return (x.abs()>z).astype(int)
def sess(d,h0=(20,7),h1=8):
    hr=pd.Series(d.index.hour,index=d.index); inr=(hr>=h0[0])|(hr<h0[1])
    g=(inr&~inr.shift(1,fill_value=False)).cumsum()
    hi=d.high.where(inr).groupby(g).cummax().ffill(); lo=d.low.where(inr).groupby(g).cummin().ffill()
    act=(~inr)&(((hr-h0[1])%24)<h1)
    s=((d.close>hi)&act).astype(int)-((d.close<lo)&act).astype(int)
    return -s.where(s!=s.shift(1),0)
if __name__=="__main__":
    out={}
    for s in ["BTCUSDT","ETHUSDT"]:
        d=load(s)
        T={"A":bt(d,cme(d,(4,21),(0,6),0).values,maxhold=240),"B":bt(d,shock(d).values,maxhold=48),"C":bt(d,sess(d).values,maxhold=288)}
        M=pd.DataFrame({k:monthly(v)[0]*100 for k,v in T.items()}); M["sum"]=M.sum(axis=1)
        print(s); print(M.round(1).T.to_string()); print("pos:",(M>0).sum().to_dict(),"tot:",M.sum().round(1).to_dict()); print(M.corr().round(2))
