#!/usr/bin/env python3
"""
ŠAMNU AZUZI v5 — ОПЕРА С ДОРАБОТАННОЙ ДРАМАТУРГИЕЙ
Изменения относительно v4:
  · Трио = внутренний диалог Гильгамеша (динамика следует его психологическому состоянию)
  · Арии с кульминациями (build_aria): вступление → развитие → пик → разрешение
  · Речитативы между сценами (build_recit): речевые переходы
  · Лейтмотивы дифференцированы: T1 (братство/мажор), T2 (угроза/хроматика), T3 (память/синкопы)
  · Финал: D3 пандури соло ppp вместо fff
"""

import os, copy
from music21 import (
    stream, note, chord, tempo, meter, key, dynamics,
    expressions, metadata, instrument, pitch
)

OUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "SAMNU_AZUZI_v5.musicxml")

# ══════════════════════════════════════════════════════════════════════
# THEMES (same as v4)
# ══════════════════════════════════════════════════════════════════════
T1_mk = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),('E5',0.5),('D5',1),('C#5',0.5),('D5',1.5)]
T1_mt = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),('C#5',0.5),('D4',1),('B3',0.5),('A4',1.5)]
T1_bn = [('D3',1),('A3',0.5),('D4',0.5),('A3',1),('D3',0.5),('A2',0.5),('D3',1),('A2',0.5),('D3',1.5)]
# T2 — chromatic threat
T2_mk = [('C#5',0.5),('G5',0.5),('A5',0.5),('F5',0.5),('B5',1),('D#5',0.5),('G#5',0.5),('E5',1),('F5',1.5)]
T2_mt = [('A4',0.5),('G#4',0.5),('G4',0.5),('F#4',0.5),('F4',1),('E4',0.5),('D#4',0.5),('D4',1),('C#4',1.5)]
T2_bn = [('D3',1),('D3',0.5),('Eb3',0.5),('D3',1),('Eb3',0.5),('D3',0.5),('C#3',1),('D3',1.5)]
# T3 — syncopated memory
T3_mk = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),('E5',0.5),('D5',0.5),('C#5',0.5),('D5',0.5),('A4',0.5),('D5',1)]
T3_mt = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),('C#5',0.5),('D4',0.5),('B3',0.5),('A4',0.5),('F#4',0.5),('A4',1)]
T3_bn = [('D3',1),('A3',0.5),('D4',0.5),('A3',1),('D3',0.5),('A2',0.5),('D3',0.5),('A2',0.5),('D3',0.5),('D2',0.5),('D3',1)]
T4_lam = [('D4',1.5),('R',0.5),('E4',1),('R',0.5),('G4',0.5),('A4',1),('G4',0.5),('E4',1),('D4',1.5),('R',0.5),('G4',1),('A4',0.5),('C5',0.5),('D5',1),('C5',0.5),('A4',0.5),('G4',1.5),('R',0.5)]
T5_lam = [('D4',1),('E4',0.5),('G4',0.5),('A4',1),('B4',0.5),('A4',0.5),('G4',1),('F#4',0.5),('E4',0.5),('D4',1)]
T5_pan = [('A4',1),('B4',0.5),('C5',0.5),('D5',1),('E5',0.5),('D5',0.5),('C5',1),('B4',0.5),('A4',0.5),('G4',0.5),('A4',0.5)]
T6_lam = [('D4',2),('E4',1.5),('G4',1.5),('A4',1),('G4',1),('E4',1),('D4',2)]
T6_enk = [('A4',1.5),('G4',1),('E4',1),('D4',1.5),('C4',1),('A3',2),('R',1)]
T7_nin = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',1)]
T7_chu = [('A3',2),('F3',1),('G3',1),('A3',1),('C4',1),('D4',2),('A3',2)]
T8_nin = [('A4',1),('C5',1),('B4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',1),('F4',0.5),('A4',0.5),('C5',1),('B4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',2)]
T9_nin = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),('R',0.5),('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',0.5),('R',0.5),('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('F4',0.5),('E4',0.5),('D4',1)]
T10_nin= [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),('R',0.5),('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',0.5),('R',0.5),('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('F4',0.5),('E4',0.5),('D4',0.5),('C4',0.5),('D4',1.5)]
T11_s1 = [('D5',1),('F5',0.5),('E5',0.5),('D5',1),('C5',0.5),('D5',0.5),('F5',1),('G5',0.5),('A5',0.5),('G5',1),('F5',0.5),('E5',0.5),('D5',1)]
T11_s2 = [('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('A4',0.5),('C5',1),('D5',0.5),('E5',0.5),('D5',1),('C5',0.5),('B4',0.5),('A4',1)]
T12_sh = [('A4',0.75),('B4',0.5),('C5',0.75),('B4',0.5),('A4',0.5),('G4',0.75),('A4',0.5),('B4',0.5),('C5',0.75),('A4',0.5),('C5',0.75),('D5',0.5),('E5',0.75),('D5',0.5),('C5',0.5),('B4',0.75),('C5',0.5),('D5',0.5),('E5',0.75),('C5',0.5)]
T13_sh = [('A4',0.75),('C5',0.5),('B4',0.75),('A4',0.5),('G4',0.5),('A4',0.75),('B4',0.5),('C5',0.75),('A4',1)]
T13_ek = [('A4',1),('G4',0.75),('E4',0.5),('D4',0.75),('C4',0.5),('R',0.5),('D4',0.75),('E4',0.5),('G4',0.5),('A4',1)]
T14_sh = [('A4',1),('G4',0.5),('F4',0.5),('E4',1),('D4',0.5),('C4',0.5),('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',1),('G4',1),('A4',0.5),('B4',0.5),('C5',1),('B4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',2),('A5',2),('G5',1),('F5',0.5),('E5',0.5),('D5',0.5),('C5',0.5),('B4',0.5),('A4',2)]
T15_or = [('D4',0.75),('F#4',0.5),('A4',0.75),('D5',0.5),('C5',0.5),('B4',0.75),('A4',0.5),('G4',0.5),('F#4',0.75),('E4',0.5),('D4',1)]
T16_ch = [('G4',0.75),('B4',0.5),('D5',0.75),('C5',0.5),('B4',0.5),('A4',0.75),('G4',0.5),('F#4',0.5),('G4',1)]
T17_tr = [('G4',1),('B4',0.5),('D5',0.5),('G5',1),('F#5',0.5),('E5',0.5),('D5',1),('C5',0.5),('B4',0.5),('A4',0.5),('G4',1.5)]
T18_ch = [('D4',1),('E4',0.5),('G4',0.5),('A4',1),('C5',0.5),('A4',0.5),('G4',1),('E4',0.5),('D4',1.5)]
T19_hu = [('D4',0.5),('Db4',0.5),('C4',0.5),('B3',0.5),('Bb3',1),('A3',0.5),('Ab3',0.5),('G3',0.5),('F#3',0.5),('F3',1),('E3',0.5),('Eb3',0.5),('D3',2)]
T20_or = [('Bb4',1),('C5',0.75),('D5',0.75),('Eb5',1),('F5',0.75),('G5',0.75),('F5',1),('Eb5',0.75),('D5',0.75),('C5',1),('Bb4',1.75)]

# Georgian songs
TSINTS_mk = [('G4',1.5),('A4',0.5),('G4',1),('E4',2),('D4',1),('E4',1),('G4',1.5),('A4',0.5),('G4',1),('E4',2),('D4',1),('E4',1),('C4',1.5),('D4',0.5),('E4',1),('D4',2),('C4',2)]
TSINTS_mt = [('E4',2),('E4',2),('E4',2),('E4',2),('C4',2),('C4',2),('C4',2),('C4',2)]
TSINTS_bn = [('C3',4),('C3',4),('G2',4),('G2',4)]
BERI_mk = [('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),('E5',0.5),('D5',1),('C#5',0.5),('D5',0.5),('E5',1),('D5',0.5),('C#5',0.5),('B4',1),('A4',0.5),('B4',0.5),('C#5',1),('D5',1)]
BERI_mt = [('D4',1),('D4',1),('B3',1),('B3',1),('A3',1),('A3',1),('F#3',1),('F#3',1)]
BERI_bn = [('D3',2.5),('D3',2.5),('B2',2.5),('B2',2.5)]
MRAV_mk = [('A4',2),('G4',1),('F#4',1),('E4',2),('D4',2),('E4',1),('F#4',1),('G4',2),('A4',2),('B4',1),('C5',1),('B4',2),('A4',4)]
MRAV_mt = [('E4',2),('E4',2),('C4',2),('C4',2),('E4',2),('E4',2),('D4',2),('C4',2)]
MRAV_bn = [('A2',4),('A2',4),('A2',4),('A2',4)]
KHAS_mk = [('D5',1.5),('C5',0.5),('B4',1),('A4',1.5),('G4',0.5),('F#4',1),('E4',1.5),('D4',0.5),('E4',1),('F#4',1.5),('G4',0.5),('A4',1)]
KHAS_mt = [('F#4',3),('F#4',3),('E4',3),('D4',3)]
KHAS_bn = [('D3',6),('D3',6)]
NANA_mk = [('E4',2),('D4',2),('C4',2),('D4',2),('E4',2),('D4',2),('C4',2),('D4',2)]
NANA_mt = [('C4',2),('B3',2),('A3',2),('B3',2),('C4',2),('B3',2),('A3',2),('B3',2)]
NANA_bn = [('A2',4),('G2',4),('A2',4),('G2',4)]
SAMK_mk = [('G4',3),('F4',1),('E4',2),('D4',2),('C4',3),('B3',1),('C4',2),('D4',2)]
SAMK_mt = [('E4',3),('D4',1),('C4',2),('B3',2),('A3',3),('G3',1),('A3',2),('B3',2)]
SAMK_bn = [('C3',4),('G2',4),('C3',4),('G2',4)]
ODOIA_mk= [('A4',1.5),('G4',0.5),('F#4',2),('E4',2),('D4',1.5),('C4',0.5),('B3',2),('A3',2)]
ODOIA_mt= [('F#4',2),('E4',2),('D4',2),('C4',2),('B3',2),('A3',2),('G3',2),('F#3',2)]
ODOIA_bn= [('D3',4),('D3',4),('A2',4),('A2',4)]
LILE_mk = [('E5',1),('D5',1),('C5',1),('B4',1),('C5',1),('D5',1),('E5',1),('D5',1),('C5',1),('B4',1),('A4',2)]
LILE_mt = [('C5',1),('B4',1),('A4',1),('G4',1),('A4',1),('B4',1),('C5',1),('B4',1),('A4',1),('G4',1),('E4',2)]
LILE_bn = [('A4',1),('G4',1),('E4',1),('D4',1),('E4',1),('G4',1),('A4',1),('G4',1),('E4',1),('D4',1),('C4',2)]
MTIUL_mk= [('D5',0.5),('E5',0.5),('D5',0.5),('C5',0.5),('B4',1),('A4',0.5),('B4',0.5),('C5',1),('B4',0.5),('A4',0.5),('G4',1),('F#4',1)]
MTIUL_mt= [('B4',1),('A4',1),('G4',1),('F#4',1),('E4',1),('D4',1),('C4',1),('B3',1)]
MTIUL_bn= [('G3',2.5),('G3',2.5),('D3',2.5),('D3',2.5)]
VIRISH_mk=[('G4',6),('F4',2),('Eb4',4),('D4',4),('C4',4)]
VIRISH_mt=[('Eb4',6),('D4',2),('C4',4),('Bb3',4),('G3',4)]
VIRISH_bn=[('C3',8),('G2',8),('C3',8)]
REKH_mk = [('A4',2),('G4',1),('F#4',1),('E4',2),('D4',2),('E4',2),('F#4',2),('G4',2)]
REKH_mt = [('E4',2),('E4',2),('D4',2),('C4',2),('B3',2),('C4',2),('D4',2),('E4',2)]
REKH_bn = [('A2',4),('A2',4),('E2',4),('E2',4)]
CHAK_mk = [('F#5',0.5),('A5',0.5),('G5',0.5),('F#5',0.5),('E5',1),('D5',0.5),('B4',0.5),('C#5',1),('D5',0.5),('E5',0.5),('F#5',1),('E5',0.5),('D5',0.5),('C#5',1),('B4',2)]
CHAK_mt = [('D4',1.75),('D4',1.75),('B3',1.75),('B3',1.75),('A3',1.75),('A3',1.75)]
CHAK_bn = [('D3',3.5),('D3',3.5),('A2',3.5),('A2',3.5)]

LYR = {
    'T1':['ma-','ny','years...','lone-','li-','ness...','bro-','ther','hood'],
    'T2_mk':['fall-','ing...','bro-','ken...','lost...','in','dark-','ness...','gone!'],
    'T2_mt':['dark-','er...','low-','er...','fur-','ther...','far-','ther','gone...'],
    'T2_bn':['D—','—','Eb—','—','D—','—','C#—','D—','—'],
    'T3':['A-','li-','lo!','ma-','ny','years!','bro-','ther-','hood','lives','on!'],
    'T7':['Na-','na,','na-','na,','my','child,','sleep','in','peace,','now','child','sleep','rest'],
    'T8':['Hear','me','child','what','I','tell','you:','the','star','will','fall','as','your','bro-','ther','comes','soon'],
    'T9':['O-','do-','ia,','o-','do-','ia,','may','the','road','be','clear','for','you!','O-','do-','ia,','may','sun','shine','on','you!'],
    'T10':['Sam-','ku-','ra-','o,','sam-','ku-','ra-','o,','my','child,','come','back','to','me,','o-','do-','ia,','sam-','ku-','ra-','o'],
    'T11_s1':['Li-','le,','li-','le,','o-','ro-','ve-','la!','life','goes','on,','for-','ev-','er'],
    'T12':['From','moun-','tain','I','came!','I','am','fire!','I','am','air!','Come!','come!','find','me!','hear!','me!','now!','come!'],
    'T13_sh':['Gan-','da-','ga-','na,','come','to','me!','no','fear!'],
    'T13_ek':['I...','re-','mem-','ber...','some-','thing...','who','am','I?','lost'],
    'T14':['Curs-','ed','be','this','day!','I','killed','him','with','love!','I','killed','him!','now','gone','for-','ev-','er!','A—','G—','F—','E—','D—','C—','B—','A—','gone'],
    'T15':['For-','ward!','U-','ruk!','Strike!','For','the','king!','For','bro-','ther-','hood!'],
    'T16':['U-','ruk','mourns!','The','king','will','not','hear','us!'],
    'T17':['Ma-','ny','years!','ma-','ny','years!','glo-','ry','to','bro-','ther-','hood!'],
    'T18':['Rekh-','vi-','ash!','beau-','ty!','strength!'],
    'T19':['I','am','the','for-','est.','I','am','the','earth.','you','will','not','pass.'],
    'T20':['Vic-','to-','ry!','the','bull','falls!','we','stand!','Uruk!','lives!','on!'],
    'gil':['I','am','king!','two-','thirds','god!','my','walls!','my','name!','why','am','I','a-','lone?'],
    'enk':['I...','am...','I?','clay...','and','blood...','I...','am...'],
    'bro':['You','are','my','bro-','ther.','un-','til','death.'],
    'lam':['Who','are','you?!','where','is','my','bro-','ther?!'],
    'sha':['who','was','there?','who','comes?','seeks','death?'],
    'fin':['I','was.','I','am.','I','will','be.'],
    'tsints':['Tsin-','tska-','ro,','wa-','ter','flows','through','the','moun-','tains'],
    'mrav':['Mra-','val-','zha-','mier!','long','may','you','live!','our','friends!'],
    'khas':['Kha-','san-','be-','gu-','ra!','rise','and','fight!'],
    'nana':['Na-','na,','na-','na,','sleep','my','love,','sleep,','rest'],
    'odoia':['O-','do-','ia,','bless','this','road','for','all','who','walk'],
    'lile':['Li-','le,','li-','le,','dance','the','spring!','joy!'],
    'chakr':['Chak-','ru-','lo!','we','con-','quer!','rise','up!','sons','of','Uruk!'],
    'virish':['We','mourn.','Gone','now.','our','bro-','ther.'],
    'rekh':['Stand','firm.','Be','strong.','As','the','oak.'],
    'samk':['Gone','is','the','light.','Come','back','to','me.'],
    'beri':['Be-','ri,','be-','ri-','ko-','ba!','spring!','joy!'],
    'mtiul':['Mti-','u-','lu-','ri!','leap','and','turn!'],
    # Aria lyrics
    'gil_aria':['En-','ki-','du!','where','are','you?!','bro-','ther!','your','hands!','your','eyes!','why','is','the','world','si-','lent','now?','dark!','dark!','gone!','GONE!'],
    'nin_aria':['Child,','I','see','your','road.','The','wa-','ters','rise.','All','flesh','must','pass.','But','your','name,','your','name','will','not','pass.','Hear','me.','Stand.'],
    'sha_aria':['Curs-','ed','am','I.','I','woke','him.','I','pulled','him','from','the','wild.','And','now','he','dies','for','love','of','you,','Gilgamesh.','my','fault.','my','fault.'],
    'recit_enkidu':['What...','is','this?','Light?','Am','I...','a','thing','of','clay?','Or','breath?','Who','am','I?'],
    'recit_gate':['Two-','thirds','god','and','one-','third','man','stands','at','the','gate.','U-ta-na-pish-tim.','Tell','me:','how','did','you','live?'],
}

VALID_DURS = {4.0,3.0,2.0,1.5,1.0,0.75,0.5,0.25}
def _snap(d):
    best=0.25
    for c in VALID_DURS:
        if abs(c-d)<abs(best-d): best=c
    return best

def _ts_beats(ts):
    n,d=map(int,ts.split('/'))
    return n*(4.0/d)

def N(p,dur=1.0,lyr=None,oct=0,fermata=False):
    dur=_snap(float(dur))
    if p=='R': return note.Rest(quarterLength=dur)
    pk=pitch.Pitch(p)
    if oct: pk.octave+=oct
    n=note.Note(pk,quarterLength=dur)
    if lyr: n.addLyric(lyr)
    if fermata: n.expressions.append(expressions.Fermata())
    return n

def tn(pdlist,lyrics=None,dyn_str=None,oct=0):
    out=[]
    for i,(p,d) in enumerate(pdlist):
        lyr=lyrics[i] if lyrics and i<len(lyrics) else None
        out.append(N(p,d,lyr=lyr,oct=oct))
    return out

def pack(nlist,ts,ks=None,bpm=None,txt=None,dyn_str=None):
    bp=_ts_beats(ts)
    ms=[]
    m=stream.Measure()
    m.timeSignature=meter.TimeSignature(ts)
    if ks is not None: m.keySignature=key.KeySignature(ks)
    if bpm: m.insert(0,tempo.MetronomeMark(number=bpm))
    if txt: m.insert(0,expressions.TextExpression(txt))
    if dyn_str: m.insert(0,dynamics.Dynamic(dyn_str))
    used=0.0
    first=True
    for n0 in nlist:
        rem=round(bp-used,6)
        dur=round(float(n0.quarterLength),6)
        while dur>1e-9:
            take=_snap(min(dur,rem))
            if take<0.24: take=0.25
            nn=note.Rest(quarterLength=take) if isinstance(n0,note.Rest) else copy.deepcopy(n0)
            nn.quarterLength=take
            if take<dur and hasattr(nn,'lyrics'): nn.lyrics=[]
            m.append(nn)
            used=round(used+take,6); dur=round(dur-take,6)
            if round(used-bp,6)>=-1e-9:
                ms.append(m); m=stream.Measure()
                if first: first=False
                else: m.timeSignature=meter.TimeSignature(ts)
                used=0.0; rem=bp
    if used>1e-9:
        lft=round(bp-used,6)
        if lft>0.24: m.append(note.Rest(quarterLength=_snap(lft)))
        ms.append(m)
    return ms

def rfill(nlist,n_m,ts='4/4',ks=None,bpm=None,txt=None,dyn_str=None):
    bp=_ts_beats(ts)
    pb=sum(round(float(x.quarterLength),6) for x in nlist) or bp
    reps=int(n_m*bp/pb)+2
    big=[]
    for _ in range(reps): big.extend(copy.deepcopy(nlist))
    ms=pack(big,ts,ks=ks,bpm=bpm,txt=txt,dyn_str=dyn_str)[:n_m]
    while len(ms)<n_m:
        m=stream.Measure(); m.timeSignature=meter.TimeSignature(ts)
        m.append(note.Rest(quarterLength=bp)); ms.append(m)
    return ms

def drone(pitch_str,n_m,ts='4/4',dyn_str='ppp',lyr=None):
    bp=_ts_beats(ts); res=[]
    for i in range(n_m):
        m=stream.Measure(); m.timeSignature=meter.TimeSignature(ts)
        rem=bp; first=(i==0)
        while rem>1e-9:
            d=_snap(min(rem,4.0));
            if d<0.24: d=0.25
            n0=note.Note(pitch_str,quarterLength=d)
            if first: n0.expressions.append(dynamics.Dynamic(dyn_str)); first=False
            if lyr and i==0 and rem==bp: n0.addLyric(lyr)
            m.append(n0); rem=round(rem-d,6)
        res.append(m)
    return res

def piano_h(cp,n_m,ts='4/4',dyn_str='pp'):
    bp=_ts_beats(ts); res=[]
    for i in range(n_m):
        m=stream.Measure(); m.timeSignature=meter.TimeSignature(ts)
        rem=bp; first=(i==0)
        while rem>1e-9:
            d=min(rem,1.0); d=_snap(d)
            if d<0.24: d=0.25
            c=chord.Chord(cp,quarterLength=d)
            if first: c.expressions.append(dynamics.Dynamic(dyn_str)); first=False
            m.append(c); rem=round(rem-d,6)
        res.append(m)
    return res

def str_sus(pitches,n_m,ts='4/4',dyn_str='pp'):
    bp=_ts_beats(ts); res=[]
    for i in range(n_m):
        m=stream.Measure(); m.timeSignature=meter.TimeSignature(ts)
        rem=bp; first=(i==0)
        while rem>1e-9:
            d=_snap(min(rem,4.0))
            if d<0.24: d=0.25
            c=chord.Chord(pitches,quarterLength=d)
            if first: c.expressions.append(dynamics.Dynamic(dyn_str)); first=False
            m.append(c); rem=round(rem-d,6)
        res.append(m)
    return res

def add(part,mlist):
    for m in mlist: part.append(m)

def mp_part(name,inst_cls,ch):
    p=stream.Part(); p.id=name; p.partName=name
    i=inst_cls(); i.midiChannel=ch; p.insert(0,i)
    return p

# ══ ARIA BUILDER ═══════════════════════════════════════════════════════
def build_aria(part_name, theme_intro, theme_devel, climax_pitch, climax_dur,
               theme_coda, n_total, ts, ks, bpm, label,
               lyrics_intro=None, lyrics_devel=None, lyrics_coda=None,
               dyn_intro='p', dyn_devel='mf', dyn_climax='ff', dyn_coda='pp',
               coda_linear=False):
    """
    Build an aria arc: intro → development → climax note (fermata) → coda.
    Returns dict: {part_name: measure_list, ...} for Piano/Strings and the aria part.
    n_total measures split: 25% intro, 40% devel, 15% climax+tail, 20% coda.
    """
    n_i = max(4, int(n_total*0.25))
    n_d = max(4, int(n_total*0.40))
    n_c = max(2, int(n_total*0.15))
    n_k = n_total - n_i - n_d - n_c

    aria_ms = []
    # Intro
    ni = tn(theme_intro, lyrics=lyrics_intro, dyn_str=dyn_intro)
    ms = rfill(ni, n_i, ts, ks=ks, bpm=bpm, txt=label, dyn_str=dyn_intro)
    aria_ms.extend(ms)

    # Development
    nd = tn(theme_devel, lyrics=lyrics_devel, dyn_str=dyn_devel)
    ms = rfill(nd, n_d, ts, ks=ks, dyn_str=dyn_devel)
    aria_ms.extend(ms)

    # Climax: single long note with fermata
    climax_note = N(climax_pitch, climax_dur, fermata=True)
    climax_ms = pack([climax_note]*8, ts, ks=ks, dyn_str=dyn_climax)[:n_c]
    if climax_ms and climax_ms[0]:
        climax_ms[0].insert(0, dynamics.Dynamic(dyn_climax))
    aria_ms.extend(climax_ms)

    # Coda
    nk = tn(theme_coda, lyrics=lyrics_coda, dyn_str=dyn_coda)
    if coda_linear:
        # Play through once (chromatic descent / unique sequence), pad with rests
        ms = pack(nk, ts, ks=ks, dyn_str=dyn_coda)
        while len(ms) < n_k:
            m = stream.Measure(); m.timeSignature = meter.TimeSignature(ts)
            m.append(note.Rest(quarterLength=_ts_beats(ts))); ms.append(m)
        ms = ms[:n_k]
    else:
        ms = rfill(nk, n_k, ts, ks=ks, dyn_str=dyn_coda)
    aria_ms.extend(ms)

    return aria_ms[:n_total]

# ══ RECITATIVE BUILDER ════════════════════════════════════════════════
def build_recit(pitches_and_durs, n_m, ts, ks, bpm, label, lyrics=None, dyn_str='mp'):
    """Build speech-like recitative line."""
    notes = tn(pitches_and_durs, lyrics=lyrics)
    return rfill(notes, n_m, ts, ks=ks, bpm=bpm, txt=label, dyn_str=dyn_str)

# ══ SCENE BUILDER (enhanced) ═════════════════════════════════════════
def build_scene(sd, parts):
    n=sd['n_measures']; ts=sd['ts_str']; ks=sd.get('ks_int',0)
    bpm=sd.get('bpm',60); label=sd.get('label','')
    cp=sd.get('piano_chords',['D3','F3','A3']); sp=sd.get('strings_pitches',['D2','A2','D3'])
    dp=sd.get('drone_pitch','D4'); feat=sd.get('featured',{})
    pdyn=sd.get('piano_dyn','pp'); sdyn=sd.get('strings_dyn','pp')
    stage_dirs=sd.get('stage_dirs',{})  # {part_name: stage_direction_text}

    for pname,part in parts.items():
        if pname=='Piano':
            ms=piano_h(cp,n,ts,dyn_str=pdyn)
            if ms: ms[0].insert(0,meter.TimeSignature(ts)); ms[0].insert(0,key.KeySignature(ks)); ms[0].insert(0,tempo.MetronomeMark(number=bpm))
            if ms and label: ms[0].insert(0,expressions.TextExpression(label))
            if pname in stage_dirs and ms: ms[0].insert(0,expressions.TextExpression(stage_dirs[pname]))
            add(part,ms)
        elif pname=='Strings':
            ms=str_sus(sp,n,ts,dyn_str=sdyn)
            if ms: ms[0].insert(0,meter.TimeSignature(ts)); ms[0].insert(0,key.KeySignature(ks))
            if pname in stage_dirs and ms: ms[0].insert(0,expressions.TextExpression(stage_dirs[pname]))
            add(part,ms)
        elif pname in feat:
            all_n=[]
            for (nl,ly,dy,rp) in feat[pname]:
                nn=tn(nl,lyrics=ly,dyn_str=dy)
                for _ in range(rp): all_n.extend(copy.deepcopy(nn))
            ms=rfill(all_n,n,ts,ks=ks,dyn_str=feat[pname][0][2])
            if ms: ms[0].insert(0,meter.TimeSignature(ts)); ms[0].insert(0,key.KeySignature(ks))
            if pname in stage_dirs and ms: ms[0].insert(0,expressions.TextExpression(stage_dirs[pname]))
            add(part,ms)
        else:
            idyn='ppp' if pdyn in ('pp','p','ppp') else 'pp'
            ms=drone(dp,n,ts,dyn_str=idyn,lyr=None if pname in ('Lamuri','Chuniri','Panduri','Winds','Brass','Cello') else 'aah')
            if ms: ms[0].insert(0,meter.TimeSignature(ts)); ms[0].insert(0,key.KeySignature(ks))
            if pname in stage_dirs and ms: ms[0].insert(0,expressions.TextExpression(stage_dirs[pname]))
            add(part,ms)

# ══ MAIN ═════════════════════════════════════════════════════════════
def build_score():
    sc=stream.Score()
    md=metadata.Metadata(); md.title='Šamnu Azuzi v5 (სამნუ ა-ზუ-ზი)'; md.composer='Jaba Tkemaladze'
    sc.insert(0,md)

    parts={}
    def mp(name,cls,ch):
        p=mp_part(name,cls,ch); parts[name]=p; return p

    mp('Gilgamesh',         instrument.Baritone,           1)
    mp('Enkidu',            instrument.Tenor,              2)
    mp('Ninsun',            instrument.MezzoSoprano,       3)
    mp('Shamhat',           instrument.Soprano,            4)
    mp('Humbaba_Utnapishti',instrument.Bass,               5)
    mp('Mkrimani',          instrument.Soprano,            6)
    mp('Mtavari',           instrument.Tenor,              7)
    mp('Bani',              instrument.Bass,               8)
    mp('Chorus',            instrument.Choir,              9)
    mp('Lamuri',            instrument.Flute,              10)
    mp('Chuniri',           instrument.Violin,             11)
    mp('Panduri',           instrument.Violin,             12)
    mp('Strings',           instrument.StringInstrument,   13)
    mp('Winds',             instrument.WoodwindInstrument, 14)
    mp('Brass',             instrument.BrassInstrument,    15)
    mp('Cello',             instrument.Violoncello,        16)
    mp('Piano',             instrument.Piano,              17)

    GIL_AR = [('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',0.5),('G4',0.5),('F4',1),('E4',0.5),('D4',0.5),('C4',1),('D4',0.5),('E4',0.5),('F4',1),('G4',1),('A4',0.5),('Bb4',0.5),('A4',0.5),('G4',0.5)]

    # ══════════════════════════════════════════════════════════════════
    # OVERTURE — 180m
    # Trio = Gilgamesh's inner voice, barely conscious of itself
    # ══════════════════════════════════════════════════════════════════
    build_scene({'n_measures':20,'ts_str':'4/4','ks_int':-1,'bpm':50,'label':'OVERTURE — A: Uruk at rest',
        'piano_chords':['D2','F2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'ppp','strings_dyn':'ppp',
        'featured':{'Chuniri':[(T7_chu,None,'pp',1)],'Lamuri':[(T4_lam,None,'pp',1)],
            'Mkrimani':[(T1_mk,LYR['T1'],'ppp',1)],'Mtavari':[(T1_mt,LYR['T1'],'ppp',1)],'Bani':[(T1_bn,LYR['T2_bn'],'ppp',1)]},
        'stage_dirs':{'Mkrimani':'[STAGE] EQUILIBRIUM — all three visible upstage, equidistant, still — gold/silver/blue light equal — T1 ppp = world in balance'}},parts)

    build_scene({'n_measures':30,'ts_str':'4/4','ks_int':2,'bpm':60,'label':'B: Gilgamesh — the king',
        'piano_chords':['D2','F#2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'mp','strings_dyn':'mp',
        'featured':{'Gilgamesh':[(GIL_AR,LYR['gil'],'mf',1)],
            'Mkrimani':[(TSINTS_mk,LYR['tsints'],'mp',1)],'Mtavari':[(TSINTS_mt,None,'mp',1)],'Bani':[(TSINTS_bn,None,'mp',1)],
            'Chuniri':[(T5_pan,None,'mf',1)],'Panduri':[(T5_lam,None,'mf',1)]}},parts)

    build_scene({'n_measures':30,'ts_str':'5/8','ks_int':-2,'bpm':58,'label':'C: Enkidu in wilderness',
        'piano_chords':['G2','Bb2','D3'],'strings_pitches':['G2','D3'],'drone_pitch':'G4','piano_dyn':'pp','strings_dyn':'pp',
        'featured':{'Enkidu':[(T6_enk,LYR['enk'],'p',1)],'Lamuri':[(T4_lam,None,'p',1)],'Chuniri':[(T6_lam,None,'pp',1)],
            'Chorus':[(ODOIA_mk,LYR['odoia'],'pp',1)],
            'Mkrimani':[(T2_mk,LYR['T2_mk'],'ppp',1)],'Mtavari':[(T2_mt,LYR['T2_mt'],'ppp',1)],'Bani':[(T2_bn,LYR['T2_bn'],'ppp',1)]}},parts)
    # Note: Trio sings T2 (threat/chromatic) — Gilgamesh's anxiety about the unknown

    build_scene({'n_measures':40,'ts_str':'5/8','ks_int':-1,'bpm':92,'label':'D: Conflict',
        'piano_chords':['D2','F2','A2'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'f','strings_dyn':'f',
        'featured':{'Gilgamesh':[(T15_or,LYR['T15'],'ff',1)],'Enkidu':[(T15_or,LYR['T15'],'ff',1)],
            'Chorus':[(T16_ch,LYR['T16'],'fff',1)],
            'Mkrimani':[(BERI_mk,LYR['beri'],'f',1)],'Mtavari':[(BERI_mt,None,'f',1)],'Bani':[(BERI_bn,None,'f',1)],
            'Winds':[(T15_or,None,'ff',1)],'Brass':[(T20_or,None,'fff',1)],'Lamuri':[(KHAS_mk,None,'ff',1)]}},parts)

    build_scene({'n_measures':30,'ts_str':'4/4','ks_int':1,'bpm':72,'label':'E: Reconciliation',
        'piano_chords':['G2','B2','D3','G3'],'strings_pitches':['G2','D3','G3'],'drone_pitch':'G4','piano_dyn':'mp','strings_dyn':'mp',
        'featured':{'Gilgamesh':[(T17_tr,LYR['T17'],'f',1)],'Enkidu':[(T17_tr,LYR['T17'],'f',1)],
            'Chorus':[(T18_ch,LYR['T18'],'mf',1)],
            'Mkrimani':[(MRAV_mk,LYR['mrav'],'mf',1)],'Mtavari':[(MRAV_mt,None,'mf',1)],'Bani':[(MRAV_bn,None,'mf',1)],
            'Chuniri':[(T5_pan,None,'mp',1)],'Panduri':[(T5_lam,None,'mp',1)],'Lamuri':[(T5_lam,None,'mp',1)]}},parts)
    # Trio: T1 returns — unity

    build_scene({'n_measures':30,'ts_str':'4/4','ks_int':-1,'bpm':50,'label':'F: Ninsun coda',
        'piano_chords':['D2','F2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'ppp','strings_dyn':'ppp',
        'featured':{'Ninsun':[(T7_nin,LYR['T7'],'mp',1),(T8_nin,LYR['T8'],'p',1)],
            'Chuniri':[(T7_chu,None,'pp',1)],
            'Mkrimani':[(T1_mk,LYR['T1'],'ppp',1)],'Mtavari':[(T1_mt,LYR['T1'],'ppp',1)],'Bani':[(T1_bn,LYR['T2_bn'],'ppp',1)],
            'Chorus':[(NANA_mk,LYR['nana'],'ppp',1)]}},parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT I — 450m
    # ══════════════════════════════════════════════════════════════════
    build_scene({'n_measures':120,'ts_str':'5/8','ks_int':-2,'bpm':58,'label':'ACT I — Sc.1: Uruk oppressed',
        'piano_chords':['G2','Bb2','D3','G3'],'strings_pitches':['G2','D3','G3'],'drone_pitch':'G4','piano_dyn':'mp','strings_dyn':'mp',
        'featured':{'Chorus':[(T16_ch,LYR['T16'],'mf',1),(BERI_mk,LYR['beri'],'f',1)],
            'Gilgamesh':[(GIL_AR,LYR['gil'],'f',1)],
            'Ninsun':[(T7_nin,LYR['T7'],'p',1)],
            'Mkrimani':[(T1_mk,LYR['T1'],'pp',1),(TSINTS_mk,LYR['tsints'],'ppp',1)],
            'Mtavari':[(T1_mt,LYR['T1'],'pp',1),(TSINTS_mt,None,'ppp',1)],
            'Bani':[(T1_bn,LYR['T2_bn'],'pp',1),(TSINTS_bn,None,'ppp',1)],
            'Lamuri':[(T4_lam,None,'p',1)],'Chuniri':[(T7_chu,None,'pp',1)],'Winds':[(T16_ch,None,'mf',1)]},
        'stage_dirs':{
            'Bani':'[STAGE] BANI steps half a step forward — Parent asserts authority — gold light brightens',
            'Mkrimani':'[STAGE] MKRIMANI crouches slightly, averts eyes downward — Child subdued under tyrant-king'}},parts)

    # Recitative: Enkidu awakens (10m)
    RECIT_ENK = [('A4',1),('G4',0.5),('A4',0.5),('C5',1),('B4',0.5),('A4',1),('G4',0.5),
                 ('E4',1),('D4',0.5),('E4',0.5),('G4',1),('A4',1.5)]
    for pname,part in parts.items():
        if pname=='Enkidu':
            ms=rfill(tn(RECIT_ENK,lyrics=LYR['recit_enkidu'],dyn_str='p'),10,'4/4',ks=-1,bpm=52,txt='Recitative: Enkidu awakens',dyn_str='p')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms)
        elif pname=='Piano':
            ms=piano_h(['D2','F2','A2'],10,'4/4',dyn_str='ppp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1)); ms[0].insert(0,tempo.MetronomeMark(number=52)); ms[0].insert(0,expressions.TextExpression('Recitative: Enkidu awakens'))
            add(part,ms)
        elif pname=='Strings':
            ms=str_sus(['D2','A2'],10,'4/4',dyn_str='ppp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms)
        elif pname in ('Mkrimani','Mtavari','Bani'):
            # Trio silent during Enkidu's first words — Gilgamesh not present
            ms=rfill([note.Rest(quarterLength=4.0)],10,'4/4',ks=-1)
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms)
        else:
            ms=drone('D4',10,'4/4',dyn_str='ppp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms)

    build_scene({'n_measures':140,'ts_str':'4/4','ks_int':-1,'bpm':66,'label':'Sc.2: Shamhat / Enkidu wakes',
        'piano_chords':['D2','F2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'pp','strings_dyn':'pp',
        'featured':{'Enkidu':[(T6_enk,LYR['enk'],'p',1)],'Shamhat':[(T12_sh,LYR['T12'],'mf',1)],
            'Ninsun':[(T7_nin,LYR['T7'],'mp',1)],'Lamuri':[(T4_lam,None,'p',1)],'Chuniri':[(T7_chu,None,'p',1)],
            'Mkrimani':[(NANA_mk,LYR['nana'],'ppp',1),(ODOIA_mk,LYR['odoia'],'pp',1)],
            'Mtavari':[(NANA_mt,None,'ppp',1),(ODOIA_mt,None,'pp',1)],
            'Bani':[(NANA_bn,None,'ppp',1),(ODOIA_bn,None,'pp',1)],
            'Chorus':[(T11_s1,LYR['T11_s1'],'pp',1)]}},parts)
    # Trio: Nana+Odoia — Gilgamesh's unconscious dream of brother he hasn't met

    build_scene({'n_measures':90,'ts_str':'4/4','ks_int':0,'bpm':72,'label':'Sc.3a: Enkidu enters Uruk',
        'piano_chords':['A2','C3','E3','A3'],'strings_pitches':['A2','E3','A3'],'drone_pitch':'A4','piano_dyn':'mf','strings_dyn':'mp',
        'featured':{'Shamhat':[(T12_sh,LYR['T12'],'mf',1)],'Enkidu':[(T13_ek,LYR['T13_ek'],'mf',1)],
            'Gilgamesh':[(T13_sh,LYR['T13_sh'],'f',1)],
            'Mkrimani':[(LILE_mk,LYR['lile'],'mp',1)],'Mtavari':[(LILE_mt,None,'mp',1)],'Bani':[(LILE_bn,None,'mp',1)],
            'Lamuri':[(T5_lam,None,'mp',1)],'Panduri':[(T5_pan,None,'mp',1)],'Chorus':[(T16_ch,LYR['T16'],'ff',1)]}},parts)
    # Trio: Lile (dance) — joy of Gilgamesh seeing his double

    build_scene({'n_measures':80,'ts_str':'5/8','ks_int':2,'bpm':88,'label':'Sc.3b: Confrontation',
        'piano_chords':['D2','F#2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'f','strings_dyn':'f',
        'featured':{'Gilgamesh':[(T15_or,LYR['T15'],'ff',1)],'Enkidu':[(T15_or,LYR['T15'],'ff',1)],
            'Chorus':[(T16_ch,LYR['T16'],'fff',1)],
            'Mkrimani':[(KHAS_mk,LYR['khas'],'ff',1)],'Mtavari':[(KHAS_mt,None,'ff',1)],'Bani':[(KHAS_bn,None,'ff',1)],
            'Lamuri':[(MTIUL_mk,LYR['mtiul'],'ff',1)],'Winds':[(T15_or,None,'ff',1)],'Brass':[(T20_or,None,'fff',1)]},
        'stage_dirs':{
            'Mkrimani':'[STAGE] ALL THREE RISE — Trio stands fully upright — all three lights blaze — integrated battle-force — the most alive Gilgamesh has ever been'}},parts)
    # Trio: Khasanbegura fff — peak of Gilgamesh's battle-rage

    # ══════════════════════════════════════════════════════════════════
    # ACT II — 270m
    # ══════════════════════════════════════════════════════════════════
    build_scene({'n_measures':90,'ts_str':'4/4','ks_int':2,'bpm':76,'label':'ACT II — Sc.4: Brotherhood sworn',
        'piano_chords':['D2','F#2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'mf','strings_dyn':'mf',
        'featured':{'Gilgamesh':[(T17_tr,LYR['T17'],'f',1)],'Enkidu':[(T17_tr,LYR['T17'],'f',1)],
            'Chorus':[(T18_ch,LYR['T18'],'mf',1),(REKH_mk,LYR['rekh'],'mf',1)],
            'Mkrimani':[(MRAV_mk,LYR['mrav'],'f',1)],'Mtavari':[(MRAV_mt,None,'f',1)],'Bani':[(MRAV_bn,None,'f',1)],
            'Ninsun':[(T9_nin,LYR['T9'],'mp',1)],'Chuniri':[(T5_pan,None,'mf',1)],'Panduri':[(T5_lam,None,'mf',1)]}},parts)
    # Trio: Mravalzhamier f — the only moment all three voices are in unison with Gilgamesh

    build_scene({'n_measures':90,'ts_str':'5/8','ks_int':2,'bpm':92,'label':'Sc.5: Journey to Cedar',
        'piano_chords':['D2','A2','D3','F#3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'mf','strings_dyn':'mf',
        'featured':{'Gilgamesh':[(T15_or,LYR['T15'],'ff',1)],'Enkidu':[(T6_enk,LYR['T15'],'mf',1)],
            'Chorus':[(T16_ch,LYR['T16'],'f',1)],
            'Mkrimani':[(MTIUL_mk,LYR['mtiul'],'f',1)],'Mtavari':[(MTIUL_mt,None,'f',1)],'Bani':[(MTIUL_bn,None,'f',1)],
            'Lamuri':[(KHAS_mk,LYR['khas'],'ff',1)],'Winds':[(T15_or,None,'ff',1)],'Brass':[(T15_or,None,'fff',1)]}},parts)

    build_scene({'n_measures':90,'ts_str':'7/8','ks_int':-1,'bpm':108,'label':'Sc.6: Humbaba',
        'piano_chords':['D2','F2','A2'],'strings_pitches':['D2','A2'],'drone_pitch':'D3','piano_dyn':'f','strings_dyn':'mf',
        'featured':{'Humbaba_Utnapishti':[(T19_hu,LYR['T19'],'ff',1)],
            'Chorus':[(T20_or,LYR['T20'],'fff',1)],
            'Mkrimani':[(CHAK_mk,LYR['chakr'],'ff',1)],'Mtavari':[(CHAK_mt,None,'ff',1)],'Bani':[(CHAK_bn,None,'ff',1)],
            'Gilgamesh':[(T15_or,LYR['T15'],'ff',1)],'Enkidu':[(T15_or,LYR['T15'],'ff',1)],
            'Brass':[(T20_or,None,'fff',1)],'Winds':[(T19_hu,None,'f',1)],'Cello':[(VIRISH_mk,None,'mf',1)]}},parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT III — 360m
    # ══════════════════════════════════════════════════════════════════
    build_scene({'n_measures':90,'ts_str':'7/8','ks_int':-2,'bpm':116,'label':'ACT III — Sc.7: Bull of Heaven',
        'piano_chords':['Bb2','D3','F3','Bb3'],'strings_pitches':['Bb2','F3','Bb3'],'drone_pitch':'Bb3','piano_dyn':'ff','strings_dyn':'ff',
        'featured':{'Chorus':[(T20_or,LYR['T20'],'fff',1)],'Gilgamesh':[(T20_or,LYR['T20'],'ff',1)],'Enkidu':[(T20_or,LYR['T20'],'ff',1)],
            'Mkrimani':[(CHAK_mk,LYR['chakr'],'fff',1)],'Mtavari':[(CHAK_mt,None,'fff',1)],'Bani':[(CHAK_bn,None,'fff',1)],
            'Brass':[(T20_or,None,'fff',1)],'Winds':[(T15_or,None,'ff',1)],'Lamuri':[(MTIUL_mk,None,'ff',1)]}},parts)

    # Enkidu dying — Scene 8: 120m with proper lamentation arc
    build_scene({'n_measures':30,'ts_str':'4/4','ks_int':0,'bpm':52,'label':'Sc.8a: Enkidu falls ill',
        'piano_chords':['A2','C3','E3'],'strings_pitches':['A2','E3'],'drone_pitch':'A3','piano_dyn':'pp','strings_dyn':'pp',
        'featured':{'Enkidu':[(T6_enk,LYR['enk'],'p',1)],'Ninsun':[(T10_nin,LYR['T10'],'mp',1)],
            'Mkrimani':[(SAMK_mk,LYR['samk'],'p',1)],'Mtavari':[(SAMK_mt,None,'p',1)],'Bani':[(SAMK_bn,None,'p',1)],
            'Gilgamesh':[(T2_mk,LYR['T2_mk'],'mf',1)],'Chuniri':[(T7_chu,None,'pp',1)]}},parts)
    # Trio: Samkurao lamentation — Gilgamesh feels death approaching

    build_scene({'n_measures':30,'ts_str':'4/4','ks_int':0,'bpm':46,'label':'Sc.8b: Enkidu dying',
        'piano_chords':['A2','C3','E3'],'strings_pitches':['A2','E3'],'drone_pitch':'A3','piano_dyn':'ppp','strings_dyn':'ppp',
        'featured':{'Enkidu':[(T6_enk,LYR['enk'],'pp',1)],'Ninsun':[(T7_nin,LYR['T7'],'p',1)],
            'Mkrimani':[(VIRISH_mk,LYR['virish'],'pp',1)],'Mtavari':[(VIRISH_mt,None,'pp',1)],'Bani':[(VIRISH_bn,None,'pp',1)],
            'Cello':[(VIRISH_bn,None,'p',1)],'Chorus':[(NANA_mk,LYR['nana'],'ppp',1)]},
        'stage_dirs':{
            'Mkrimani':'[STAGE] MKRIMANI trembles — blue light flickers — Child feels death approaching — hands raised as if to stop it',
            'Mtavari':'[STAGE] MTAVARI looks downward — Adult unable to process — silver light dims unevenly',
            'Bani':'[STAGE] BANI does not move — Parent has always known this moment would come — gold steady but quiet'}},parts)
    # Trio: Virishkhau pp — Gilgamesh's dread

    # Bani solo — Enkidu's last breath (10m)
    for pname,part in parts.items():
        dyn_v = 'ppp'
        if pname=='Bani':
            # Bani alone: sustained D2 ppp morendo
            ms=drone('D2',10,'4/4',dyn_str='ppp',lyr='aah')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(0)); ms[0].insert(0,tempo.MetronomeMark(number=40)); ms[0].insert(0,expressions.TextExpression('Sc.8c: The last breath — Bani solo'))
            add(part,ms)
        elif pname in ('Mkrimani','Mtavari'):
            ms=rfill([note.Rest(quarterLength=4.0)],10,'4/4',ks=0)
            if ms:
                ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(0))
                if pname=='Mkrimani':
                    ms[0].insert(0,expressions.TextExpression('[STAGE] MKRIMANI FALLS — Child goes silent — blue light extinguishes — Mkrimani collapses to the floor and does not move'))
                if pname=='Mtavari':
                    ms[0].insert(0,expressions.TextExpression('[STAGE] MTAVARI freezes — Adult loses words — silver light dims'))
            add(part,ms)
        elif pname=='Piano':
            ms=piano_h(['D2','A2'],10,'4/4',dyn_str='ppp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(0)); ms[0].insert(0,tempo.MetronomeMark(number=40)); ms[0].insert(0,expressions.TextExpression('Sc.8c: The last breath'))
            add(part,ms)
        elif pname=='Strings':
            ms=str_sus(['D2'],10,'4/4',dyn_str='ppp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(0))
            add(part,ms)
        else:
            ms=rfill([note.Rest(quarterLength=4.0)],10,'4/4',ks=0)
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(0))
            add(part,ms)

    # Scene 9: Gilgamesh's grief — ARIA with climax (150m)
    # Split: 40m setup → 110m aria arc
    build_scene({'n_measures':40,'ts_str':'4/4','ks_int':-1,'bpm':56,'label':'Sc.9a: Gilgamesh grieves',
        'piano_chords':['D2','F2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'mf','strings_dyn':'mp',
        'featured':{'Shamhat':[(T14_sh,LYR['T14'],'f',1)],'Chorus':[(REKH_mk,LYR['rekh'],'mf',1)],
            'Mkrimani':[(T2_mk,LYR['T2_mk'],'f',1)],'Mtavari':[(T2_mt,LYR['T2_mt'],'f',1)],'Bani':[(T2_bn,LYR['T2_bn'],'f',1)],
            'Ninsun':[(T9_nin,LYR['T9'],'mf',1)],'Cello':[(VIRISH_mk,None,'mf',1)]}},parts)

    # Gilgamesh aria proper: 110m with F4 climax (broken breath — sings not beautifully but TRULY)
    # [STAGE] Gilgamesh kneels over Enkidu's body. The Trio is silent except Bani drone pp.
    # [CONDUCTOR] At F4 climax: broken breath — singer must fracture the note — not beautiful, TRUE.
    GIL_ARIA_INTRO  = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('Bb3',0.5),('A3',2)]
    GIL_ARIA_DEVEL  = [('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',0.5),('Bb4',0.5),('C5',1),('D5',0.5),('E5',0.5),('F5',2)]
    GIL_ARIA_CODA   = [('D4',2),('C4',1),('Bb3',1),('A3',2),('G3',2),('F3',4)]
    aria_ms = build_aria('Gilgamesh', GIL_ARIA_INTRO, GIL_ARIA_DEVEL, 'F4', 4.0, GIL_ARIA_CODA,
                         110,'4/4',-1,52,'Sc.9b: Aria — Enkidu! Where are you? [broken breath at climax — sing TRULY, not beautifully]',
                         LYR['gil_aria'],LYR['gil_aria'],LYR['fin'],'p','mf','ff','pp')
    for pname,part in parts.items():
        if pname=='Gilgamesh':
            add(part,aria_ms)
        elif pname=='Piano':
            ms=piano_h(['D2','F2','A2','D3'],110,'4/4',dyn_str='mp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1)); ms[0].insert(0,tempo.MetronomeMark(number=52)); ms[0].insert(0,expressions.TextExpression('Sc.9b: Aria'))
            add(part,ms)
        elif pname=='Strings':
            ms=str_sus(['D2','A2','D3'],110,'4/4',dyn_str='mp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms)
        elif pname=='Mkrimani':
            # Trio: T2 chromatic, then silence at climax, then T3 return
            ms=rfill(tn(T2_mk,lyrics=LYR['T2_mk'],dyn_str='mf'),80,'4/4',ks=-1,dyn_str='mf')
            ms+=rfill([note.Rest(quarterLength=4.0)],15,'4/4',ks=-1)  # silence at climax
            ms+=rfill(tn(T3_mk,lyrics=LYR['T3'],dyn_str='pp'),15,'4/4',ks=-1,dyn_str='pp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms[:110])
        elif pname=='Mtavari':
            ms=rfill(tn(T2_mt,lyrics=LYR['T2_mt'],dyn_str='mf'),80,'4/4',ks=-1,dyn_str='mf')
            ms+=rfill([note.Rest(quarterLength=4.0)],15,'4/4',ks=-1)
            ms+=rfill(tn(T3_mt,dyn_str='pp'),15,'4/4',ks=-1,dyn_str='pp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms[:110])
        elif pname=='Bani':
            ms=rfill(tn(T2_bn,lyrics=LYR['T2_bn'],dyn_str='mf'),80,'4/4',ks=-1,dyn_str='mf')
            ms+=rfill([note.Rest(quarterLength=4.0)],15,'4/4',ks=-1)
            ms+=rfill(tn(T3_bn,dyn_str='pp'),15,'4/4',ks=-1,dyn_str='pp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms[:110])
        else:
            ms=drone('D4',110,'4/4',dyn_str='pp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(-1))
            add(part,ms)

    # ══════════════════════════════════════════════════════════════════
    # ACT IV — 540m
    # ══════════════════════════════════════════════════════════════════
    build_scene({'n_measures':120,'ts_str':'4/4','ks_int':-1,'bpm':46,'label':'ACT IV — Sc.10: Underworld',
        'piano_chords':['D2','F2','Ab2'],'strings_pitches':['D2','Ab2'],'drone_pitch':'D3','piano_dyn':'ppp','strings_dyn':'ppp',
        'featured':{'Gilgamesh':[(T19_hu,LYR['sha'],'mf',1)],
            'Humbaba_Utnapishti':[(T19_hu,LYR['T19'],'p',1)],
            'Mkrimani':[(VIRISH_mk,LYR['virish'],'pp',1)],'Mtavari':[(VIRISH_mt,None,'pp',1)],'Bani':[(VIRISH_bn,None,'pp',1)],
            'Chorus':[(T2_mk,LYR['T2_mk'],'pp',1)],'Cello':[(VIRISH_bn,None,'p',1)],'Chuniri':[(T19_hu,None,'pp',1)]},
        'stage_dirs':{
            'Mkrimani':'[STAGE] TRIO BARELY VISIBLE — each isolated in separate darkness — no common light — identity dissolving — Virishkhau Eb-minor — the Child is almost gone',
            'Mtavari':'[STAGE] MTAVARI sits on floor — Adult consciousness fragmenting in the underworld',
            'Bani':'[STAGE] BANI still standing but turned away — even the Parent loses orientation in the land of the dead'}},parts)
    # Trio: Virishkhau ppp — Gilgamesh in the underworld, stripped of identity

    # Recitative: Gilgamesh at Utnapishti's gate (15m)
    # СТАККАТНЫЙ РЕЧИТАТИВ: сухие короткие фразы → 4 такта тишины → ответ из тишины
    # [STAGE] Gilgamesh stands at the edge of the world. Stillness.
    # Each short phrase = a stone placed carefully. Then: SILENCE. Then Utnapishti speaks.
    RECIT_GATE_STAC = [
        ('D4',0.25),('R',0.5),('G4',0.25),('R',0.5),('F4',0.25),('R',2.25),  # "Two-thirds god—"
        ('E4',0.25),('R',0.5),('D4',0.25),('R',0.5),('C4',0.25),('R',2.25),  # "—stands at the gate."
        ('G4',0.25),('R',0.5),('A4',0.25),('R',3.0),                           # "U-ta-na-pish-tim."
        ('F4',0.25),('R',0.5),('E4',0.25),('R',0.5),('D4',0.25),('R',2.25),  # "Tell me:"
        ('D4',0.5),('E4',0.25),('F4',0.25),('R',3.0),                          # "how did you live?"
    ]
    RECIT_GATE_LYR = ['Two-','','thirds—','','god—','', 'stands','','at','','gate.','',
                      'U-ta-','','napish-tim!','', 'Tell','','me:','','how','',
                      'did','you','live?','']
    # Utnapishti speaks after 4 measures of total silence
    RECIT_UTA = [('G3',0.5),('R',0.5),('A3',0.5),('R',0.5),('B3',1),('R',1),
                 ('C4',0.5),('R',0.5),('D4',1),('R',2)]
    RECIT_UTA_LYR = ['I','','lived','','once.','','Now','','I','watch.']
    for pname,part in parts.items():
        if pname=='Gilgamesh':
            # 5m staccato + 4m silence + 1m echo = 10m, pad to 15m
            ms = pack(tn(RECIT_GATE_STAC, lyrics=RECIT_GATE_LYR, dyn_str='mp'),'4/4',ks=1)[:5]
            ms += rfill([note.Rest(quarterLength=4.0)],4,'4/4',ks=1)
            ms += rfill(tn([('D4',0.5),('R',3.5)],dyn_str='pp'),6,'4/4',ks=1,dyn_str='pp')
            ms = ms[:15]
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1)); ms[0].insert(0,tempo.MetronomeMark(number=46)); ms[0].insert(0,expressions.TextExpression('Recitative: At the gate of Utnapishti [staccato — dry — stillness]'))
            add(part,ms)
        elif pname=='Humbaba_Utnapishti':
            # Silent for 9m, then speaks from silence (m10–13), then silence
            ms = rfill([note.Rest(quarterLength=4.0)],9,'4/4',ks=1)
            ms += pack(tn(RECIT_UTA, lyrics=RECIT_UTA_LYR, dyn_str='p'),'4/4',ks=1)[:4]
            ms += rfill([note.Rest(quarterLength=4.0)],2,'4/4',ks=1)
            ms = ms[:15]
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1)); ms[9].insert(0,expressions.TextExpression('[STAGE: Utnapishti speaks from total silence]'))
            add(part,ms)
        elif pname=='Piano':
            # Single chord stabs — then silence matching Gilgamesh's rests
            stab = chord.Chord(['G2','B2','D3'], quarterLength=0.25)
            ms_stab = []
            for i in range(5):
                m = stream.Measure(); m.timeSignature = meter.TimeSignature('4/4')
                m.append(copy.deepcopy(stab)); m.append(note.Rest(quarterLength=3.75)); ms_stab.append(m)
            ms = ms_stab + rfill([note.Rest(quarterLength=4.0)],10,'4/4',ks=1)
            ms = ms[:15]
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1)); ms[0].insert(0,tempo.MetronomeMark(number=46)); ms[0].insert(0,dynamics.Dynamic('ppp')); ms[0].insert(0,expressions.TextExpression('Recitative: At the gate'))
            add(part,ms)
        elif pname=='Strings':
            ms=str_sus(['G2','D3'],5,'4/4',dyn_str='ppp') + rfill([note.Rest(quarterLength=4.0)],10,'4/4',ks=1)
            ms=ms[:15]
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            add(part,ms)
        elif pname=='Panduri':
            # Single D3 ppp in the silence — like a heartbeat
            ms = rfill([note.Rest(quarterLength=4.0)],8,'4/4',ks=1)
            single = stream.Measure(); single.timeSignature = meter.TimeSignature('4/4')
            pn = note.Note('D3', quarterLength=0.5); pn.expressions.append(dynamics.Dynamic('ppp'))
            single.append(pn); single.append(note.Rest(quarterLength=3.5)); ms.append(single)
            ms += rfill([note.Rest(quarterLength=4.0)],6,'4/4',ks=1)
            ms = ms[:15]
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            add(part,ms)
        elif pname in ('Mkrimani','Mtavari','Bani'):
            # Trio: T3 memory fragments pp — Gilgamesh remembers Enkidu
            theme = T3_mk if pname=='Mkrimani' else (T3_mt if pname=='Mtavari' else T3_bn)
            ms=rfill(tn(theme,dyn_str='pp'),15,'4/4',ks=1,dyn_str='pp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            if pname=='Mkrimani' and ms: ms[0].insert(0,expressions.TextExpression('[STAGE] Mkrimani barely visible — memory of Enkidu fragments'))
            add(part,ms)
        else:
            ms=drone('G3',15,'4/4',dyn_str='ppp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            add(part,ms)

    # Ninsun aria — prophecy (120m)
    NIN_ARIA_INTRO = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),('F4',1),('G4',0.5),('A4',0.5),('G4',1)]
    NIN_ARIA_DEVEL = [('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('F4',0.5),('E4',1),('D4',0.5),('F4',0.5),('A4',1),('C5',1),('E5',2)]
    NIN_ARIA_CODA  = [('D4',2),('E4',1),('F4',1),('G4',2),('A4',2),('D4',4)]
    nin_aria = build_aria('Ninsun', NIN_ARIA_INTRO, NIN_ARIA_DEVEL, 'E5', 3.0, NIN_ARIA_CODA,
                          120,'4/4',1,58,'Sc.11: Aria Ninsun — the waters rise',
                          LYR['nin_aria'],LYR['nin_aria'],LYR['fin'],'p','f','ff','pp')
    for pname,part in parts.items():
        if pname=='Ninsun': add(part,nin_aria)
        elif pname=='Humbaba_Utnapishti':
            ms=rfill(tn(T8_nin,lyrics=LYR['T8'],dyn_str='mf'),120,'4/4',ks=1,bpm=58,txt='Sc.11: Utnapishti tells the flood',dyn_str='mf')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            add(part,ms)
        elif pname=='Piano':
            ms=piano_h(['G2','B2','D3','G3'],120,'4/4',dyn_str='mp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1)); ms[0].insert(0,tempo.MetronomeMark(number=58)); ms[0].insert(0,expressions.TextExpression('Sc.11'))
            add(part,ms)
        elif pname=='Strings':
            ms=str_sus(['G2','D3','G3'],120,'4/4',dyn_str='mp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            add(part,ms)
        elif pname=='Mkrimani':
            ms=rfill(tn(TSINTS_mk,lyrics=LYR['tsints'],dyn_str='mp'),120,'4/4',ks=1,dyn_str='mp')
            if ms:
                ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
                ms[0].insert(0,expressions.TextExpression('[STAGE] MKRIMANI SLOWLY RISES FROM THE FLOOR — first movement since Enkidu\'s death — blue light returns — Child remembers — Tsintskaro: the water that was always flowing'))
            add(part,ms)
        elif pname=='Mtavari':
            ms=rfill(tn(TSINTS_mt,dyn_str='mp'),120,'4/4',ks=1,dyn_str='mp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            add(part,ms)
        elif pname=='Bani':
            ms=rfill(tn(TSINTS_bn,dyn_str='mp'),120,'4/4',ks=1,dyn_str='mp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            add(part,ms)
        else:
            ms=drone('G3',120,'4/4',dyn_str='mp')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(1))
            add(part,ms)
    # Trio: Tsintskaro — memory of the beginning. Gilgamesh returning to where he started

    # Shamhat aria of guilt (150m)
    # Coda = 2-octave chromatic descent A5→A3 — each semitone = a stage of falling
    # "башня из звуков, которая рушится" (tower of sounds collapsing)
    SHA_ARIA_INTRO = [('A4',1),('G4',0.5),('F4',0.5),('E4',1),('D4',0.5),('C4',0.5),('B3',2)]
    SHA_ARIA_DEVEL = T14_sh
    SHA_ARIA_CODA  = [
        ('A5',1.5),  # peak — "I am cursed"
        ('Ab5',1),('G5',1),('F#5',1),('F5',1.5),      # "I woke him..."
        ('E5',1),('Eb5',1),('D5',1),('Db5',1.5),       # "I called him..."
        ('C5',1),('B4',1),('Bb4',1.5),                  # "I gave him civilization..."
        ('A4',2),('Ab4',1.5),('G4',2),                  # "I gave him death..."
        ('F#4',1.5),('F4',2),('E4',2),                  # "he trusted me..."
        ('Eb4',2),('D4',2),('Db4',2),                   # "he followed me..."
        ('C4',3),('B3',3),                               # "my fault..."
        ('Bb3',4),('A3',4),                              # "my fault... gone."
    ]
    SHA_ARIA_CODA_LYRICS = [
        'curs-','ed...','I...','woke...','him...','I...',
        'called...','him...','I...','gave...','him...','life...',
        'I...','gave...','death...','he...','trust-','ed...',
        'he...','fol-','lowed...','my...','fault...',
        'my fault...','gone.'
    ]
    sha_aria = build_aria('Shamhat', SHA_ARIA_INTRO, SHA_ARIA_DEVEL, 'A5', 2.0, SHA_ARIA_CODA,
                          150,'4/4',2,66,'Sc.12: Aria Shamhat — my fault',
                          LYR['sha_aria'],LYR['T14'],SHA_ARIA_CODA_LYRICS,'p','f','ff','pp',
                          coda_linear=True)
    for pname,part in parts.items():
        if pname=='Shamhat': add(part,sha_aria)
        elif pname=='Chorus':
            ms=rfill(tn(T11_s1,lyrics=LYR['T11_s1'],dyn_str='mf'),150,'4/4',ks=2,bpm=66,txt='Sc.12: Wisdom',dyn_str='mf')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
            add(part,ms)
        elif pname=='Gilgamesh':
            ms=rfill(tn(T17_tr,lyrics=LYR['T17'],dyn_str='ff'),150,'4/4',ks=2,dyn_str='ff')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
            add(part,ms)
        elif pname=='Piano':
            ms=piano_h(['D2','F#2','A2','D3'],150,'4/4',dyn_str='mf')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2)); ms[0].insert(0,tempo.MetronomeMark(number=66)); ms[0].insert(0,expressions.TextExpression('Sc.12'))
            add(part,ms)
        elif pname=='Strings':
            ms=str_sus(['D2','A2','D3'],150,'4/4',dyn_str='mf')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
            add(part,ms)
        elif pname=='Mkrimani':
            ms=rfill(tn(MRAV_mk,lyrics=LYR['mrav'],dyn_str='ff'),150,'4/4',ks=2,dyn_str='ff')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
            add(part,ms)
        elif pname=='Mtavari':
            ms=rfill(tn(MRAV_mt,dyn_str='ff'),150,'4/4',ks=2,dyn_str='ff')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
            add(part,ms)
        elif pname=='Bani':
            ms=rfill(tn(MRAV_bn,dyn_str='ff'),150,'4/4',ks=2,dyn_str='ff')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
            add(part,ms)
        else:
            ms=drone('D4',150,'4/4',dyn_str='mf')
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
            add(part,ms)
    # Trio: Mravalzhamier fff — acceptance and majesty

    # Return to Uruk (70m)
    build_scene({'n_measures':70,'ts_str':'4/4','ks_int':2,'bpm':72,'label':'Sc.13: Return to Uruk',
        'piano_chords':['D2','F#2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'f','strings_dyn':'f',
        'featured':{'Gilgamesh':[(T1_mk,LYR['T1'],'ff',1),(T3_mk,LYR['T3'],'f',1)],
            'Chorus':[(T18_ch,LYR['T18'],'ff',1),(MRAV_mk,LYR['mrav'],'fff',1)],
            'Mkrimani':[(T1_mk,LYR['T1'],'fff',1)],'Mtavari':[(T1_mt,LYR['T1'],'fff',1)],'Bani':[(T1_bn,LYR['T2_bn'],'fff',1)],
            'Ninsun':[(T8_nin,LYR['T8'],'f',1)],'Lamuri':[(T5_lam,None,'ff',1)],
            'Chuniri':[(T5_pan,None,'ff',1)],'Panduri':[(T5_pan,None,'ff',1)],
            'Winds':[(T20_or,None,'ff',1)],'Brass':[(T20_or,None,'fff',1)]},
        'stage_dirs':{
            'Mkrimani':'[STAGE] TRIO FULLY REUNITED — all three standing together, equidistant — all lights blazing as one — INTEGRATED SELF — Gilgamesh is whole, but changed — the armor is gone'}},parts)
    # Trio T1 fff — Gilgamesh whole again, but changed

    # Epilogue: Chakrulo fades → final D3 Panduri ppp (60m)
    build_scene({'n_measures':55,'ts_str':'5/8','ks_int':2,'bpm':100,'label':'Epilogue: The walls of Uruk endure',
        'piano_chords':['D2','F#2','A2','D3'],'strings_pitches':['D2','A2','D3'],'drone_pitch':'D4','piano_dyn':'fff','strings_dyn':'ff',
        'featured':{'Chorus':[(T20_or,LYR['T20'],'fff',1),(CHAK_mk,LYR['chakr'],'fff',1)],
            'Gilgamesh':[(T20_or,LYR['T20'],'fff',1)],
            'Enkidu':[(T17_tr,LYR['fin'],'ff',1)],  # ghost echo
            'Mkrimani':[(TSINTS_mk,LYR['tsints'],'ff',1)],'Mtavari':[(TSINTS_mt,None,'ff',1)],'Bani':[(TSINTS_bn,None,'ff',1)],
            'Brass':[(T20_or,None,'fff',1)],'Winds':[(T20_or,None,'ff',1)],'Lamuri':[(KHAS_mk,None,'ff',1)]},
        'stage_dirs':{
            'Mkrimani':'[STAGE] TRIO STEPS BACKWARD — slowly — returning into Gilgamesh\'s mind — as the chorus swells they recede — last: Mkrimani (Child) turns away first — the dream ends'}},parts)

    # FINAL 5 MEASURES: Panduri solo D3 ppp morendo
    for pname,part in parts.items():
        if pname=='Panduri':
            ms=drone('D3',5,'4/4',dyn_str='ppp',lyr=None)
            if ms:
                ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
                ms[0].insert(0,tempo.MetronomeMark(number=40))
                ms[0].insert(0,expressions.TextExpression('morendo — Panduri solo'))
                ms[0].insert(0,dynamics.Dynamic('ppp'))
            add(part,ms)
        elif pname=='Piano':
            ms=rfill([note.Rest(quarterLength=4.0)],5,'4/4',ks=2)
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2)); ms[0].insert(0,tempo.MetronomeMark(number=40)); ms[0].insert(0,expressions.TextExpression('morendo'))
            add(part,ms)
        else:
            ms=rfill([note.Rest(quarterLength=4.0)],5,'4/4',ks=2)
            if ms: ms[0].insert(0,meter.TimeSignature('4/4')); ms[0].insert(0,key.KeySignature(2))
            add(part,ms)

    for pname,part in parts.items():
        sc.insert(0,part)

    total=max(len([m for m in p.getElementsByClass(stream.Measure)]) for p in sc.parts)
    print(f"Total measures: {total}")
    return sc

def main():
    print("Building Šamnu Azuzi v5...")
    sc=build_score()
    print(f"Writing {OUT_FILE}...")
    sc.write('musicxml', fp=OUT_FILE)
    sz=os.path.getsize(OUT_FILE)
    print(f"Done. Size: {sz/1024/1024:.1f} MB")

if __name__=='__main__':
    main()
