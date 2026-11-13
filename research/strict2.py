import sys; sys.path.insert(0,"/home/user/mohammad1/research"); sys.path.insert(0,"/home/user/mohammad1")
import io, contextlib
with contextlib.redirect_stdout(io.StringIO()): from strict1 import *
print("--- filter combinations (original exits)")
C1=dict(vol=0.8,tr2="tr30",conf=1,wvol=2.5)
test("A: trend30+confl1 | whale vol2.5",C1)
test("B: A + whale shock1",dict(C1,wshock=1))
test("C: A + vol<=0.6",dict(C1,vol=0.6))
test("D: A + whale z2.5",dict(C1,wz=2.5))
test("E: A + trend7 on S3",dict(C1,tr3="tr7"))
print("--- strict set A with different exits: SL x a, TP = b x SL")
for a,b in [(1,4),(1,3),(1,2),(1,1.5),(1,1),(1.5,2),(1.5,1.5),(1.5,1),(2,1.5),(2,1),(2,0.75),(3,0.5)]:
    sl={k:v*a for k,v in SLx.items()}; tp={k:sl[k]*b for k in sl}
    if (a,b)==(1,4): tp=TPx
    test(f"SLx{a} TP={b}xSL",C1,sl,tp)
