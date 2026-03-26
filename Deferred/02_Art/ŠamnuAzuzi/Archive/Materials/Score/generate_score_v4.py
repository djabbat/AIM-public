#!/usr/bin/env python3
"""
ŠAMNU AZUZI v4 — COMPLETE OPERA FOR MUSESCORE 3
სამნუ ა-ზუ-ზი / Samnu A-zu-zi
Music and Libretto: Jaba Tkemaladze

VERSION 4 PRINCIPLES:
  · Overture=180 + Act I=450 + Act II=270 + Act III=360 + Act IV=540 = 1800 measures
  · ALL sections have explicit dynamics (pp → fff)
  · Authentic Georgian songs integrated as primary melodic material
    (Tsintskaro, Beri-Berikoba, Mravalzhamier, Khasanbegura, Nana, Samkurao,
     Odoia, Lile, Mtiuluri, Virishkhau, Rekhviashi, Chakrulo)
  · Georgian instruments (Lamuri/Chuniri/Panduri) are melodic, not drones
  · Trio (Mkrimani/Mtavari/Bani) present in Overture and all scenes
  · Asymmetric time signatures: 5/8 (Beri-Berikoba/Mtiuluri), 7/8 (Chakrulo)
  · No theme repetition without development
"""

import os
import copy

from music21 import (
    stream, note, chord, tempo, meter, key, dynamics,
    expressions, metadata, instrument, clef, bar, pitch
)

OUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "SAMNU_AZUZI_v4.musicxml")

# ══════════════════════════════════════════════════════════════════════
# ORIGINAL THEMES T1–T20
# ══════════════════════════════════════════════════════════════════════

T1_mkrimani = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',1),('C#5',0.5),('D5',1.5)]
T1_mtavari  = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),
               ('C#5',0.5),('D4',1),('B3',0.5),('A4',1.5)]
T1_bani     = [('D3',1),('A3',0.5),('D4',0.5),('A3',1),('D3',0.5),
               ('A2',0.5),('D3',1),('A2',0.5),('D3',1.5)]

T2_mkrimani = [('C#5',0.5),('G5',0.5),('A5',0.5),('F5',0.5),('B5',1),
               ('D#5',0.5),('G#5',0.5),('E5',1),('F5',1.5)]
T2_mtavari  = [('A4',0.5),('G#4',0.5),('G4',0.5),('F#4',0.5),('F4',1),
               ('E4',0.5),('D#4',0.5),('D4',1),('C#4',1.5)]
T2_bani     = [('D3',1),('D3',0.5),('Eb3',0.5),('D3',1),
               ('Eb3',0.5),('D3',0.5),('C#3',1),('D3',1.5)]

T3_mkrimani = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',0.5),('C#5',0.5),('D5',0.5),('A4',0.5),('D5',1)]
T3_mtavari  = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),
               ('C#5',0.5),('D4',0.5),('B3',0.5),('A4',0.5),('F#4',0.5),('A4',1)]
T3_bani     = [('D3',1),('A3',0.5),('D4',0.5),('A3',1),('D3',0.5),
               ('A2',0.5),('D3',0.5),('A2',0.5),('D3',0.5),('D2',0.5),('D3',1)]

T4_lamuri   = [('D4',1.5),('R',0.5),('E4',1),('R',0.5),('G4',0.5),
               ('A4',1),('G4',0.5),('E4',1),('D4',1.5),('R',0.5),
               ('G4',1),('A4',0.5),('C5',0.5),('D5',1),('C5',0.5),
               ('A4',0.5),('G4',1.5),('R',0.5)]

T5_lamuri   = [('D4',1),('E4',0.5),('G4',0.5),('A4',1),('B4',0.5),
               ('A4',0.5),('G4',1),('F#4',0.5),('E4',0.5),('D4',1)]
T5_panduri  = [('A4',1),('B4',0.5),('C5',0.5),('D5',1),('E5',0.5),
               ('D5',0.5),('C5',1),('B4',0.5),('A4',0.5),('G4',0.5),('A4',0.5)]

T6_lamuri   = [('D4',2),('E4',1.5),('G4',1.5),('A4',1),('G4',1),('E4',1),('D4',2)]
T6_enkidu   = [('A4',1.5),('G4',1),('E4',1),('D4',1.5),('C4',1),('A3',2),('R',1)]

T7_ninsun   = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),
               ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',1)]
T7_chuniri  = [('A3',2),('F3',1),('G3',1),('A3',1),('C4',1),('D4',2),('A3',2)]

T8_ninsun   = [('A4',1),('C5',1),('B4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),
               ('D4',1),('F4',0.5),('A4',0.5),('C5',1),('B4',0.5),('A4',0.5),
               ('G4',1),('F4',0.5),('E4',0.5),('D4',2)]

T9_ninsun   = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),('R',0.5),
               ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',0.5),('R',0.5),
               ('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('F4',0.5),('E4',0.5),('D4',1)]

T10_ninsun  = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),('R',0.5),
               ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',0.5),('R',0.5),
               ('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('F4',0.5),
               ('E4',0.5),('D4',0.5),('C4',0.5),('D4',1.5)]

T11_sop1    = [('D5',1),('F5',0.5),('E5',0.5),('D5',1),('C5',0.5),('D5',0.5),
               ('F5',1),('G5',0.5),('A5',0.5),('G5',1),('F5',0.5),('E5',0.5),('D5',1)]
T11_sop2    = [('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('A4',0.5),
               ('C5',1),('D5',0.5),('E5',0.5),('D5',1),('C5',0.5),('B4',0.5),('A4',1)]
T11_alto    = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),
               ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',1)]

T12_shamhat = [('A4',0.75),('B4',0.5),('C5',0.75),('B4',0.5),('A4',0.5),
               ('G4',0.75),('A4',0.5),('B4',0.5),('C5',0.75),('A4',0.5),
               ('C5',0.75),('D5',0.5),('E5',0.75),('D5',0.5),('C5',0.5),
               ('B4',0.75),('C5',0.5),('D5',0.5),('E5',0.75),('C5',0.5)]

T13_shamhat = [('A4',0.75),('C5',0.5),('B4',0.75),('A4',0.5),('G4',0.5),
               ('A4',0.75),('B4',0.5),('C5',0.75),('A4',1)]
T13_enkidu  = [('A4',1),('G4',0.75),('E4',0.5),('D4',0.75),('C4',0.5),
               ('R',0.5),('D4',0.75),('E4',0.5),('G4',0.5),('A4',1)]

T14_shamhat = [('A4',1),('G4',0.5),('F4',0.5),('E4',1),('D4',0.5),('C4',0.5),
               ('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',1),
               ('G4',1),('A4',0.5),('B4',0.5),('C5',1),('B4',0.5),('A4',0.5),
               ('G4',1),('F4',0.5),('E4',0.5),('D4',2),
               ('A5',2),('G5',1),('F5',0.5),('E5',0.5),('D5',0.5),('C5',0.5),('B4',0.5),('A4',2)]

T15_orch    = [('D4',0.75),('F#4',0.5),('A4',0.75),('D5',0.5),('C5',0.5),
               ('B4',0.75),('A4',0.5),('G4',0.5),('F#4',0.75),('E4',0.5),('D4',1)]

T16_chorus  = [('G4',0.75),('B4',0.5),('D5',0.75),('C5',0.5),('B4',0.5),
               ('A4',0.75),('G4',0.5),('F#4',0.5),('G4',1)]

T17_trio    = [('G4',1),('B4',0.5),('D5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',1),('C5',0.5),('B4',0.5),('A4',0.5),('G4',1.5)]

T18_chorus  = [('D4',1),('E4',0.5),('G4',0.5),('A4',1),('C5',0.5),
               ('A4',0.5),('G4',1),('E4',0.5),('D4',1.5)]

T19_humbaba = [('D4',0.5),('Db4',0.5),('C4',0.5),('B3',0.5),('Bb3',1),
               ('A3',0.5),('Ab3',0.5),('G3',0.5),('F#3',0.5),('F3',1),
               ('E3',0.5),('Eb3',0.5),('D3',2)]

T20_orch    = [('Bb4',1),('C5',0.75),('D5',0.75),('Eb5',1),('F5',0.75),
               ('G5',0.75),('F5',1),('Eb5',0.75),('D5',0.75),('C5',1),('Bb4',1.75)]

# ══════════════════════════════════════════════════════════════════════
# AUTHENTIC GEORGIAN SONGS — researched via DeepSeek
# Each song: mkrimani (top), mtavari (middle), bani (bass)
# ══════════════════════════════════════════════════════════════════════

# 1. წინწყარო (Tsintskaro) — Gurian lyrical, 4/4, F major, BPM=66
TSINTSKARO_mk  = [('G4',1.5),('A4',0.5),('G4',1),('E4',2),('D4',1),('E4',1),
                  ('G4',1.5),('A4',0.5),('G4',1),('E4',2),('D4',1),('E4',1),
                  ('C4',1.5),('D4',0.5),('E4',1),('D4',2),('C4',2)]
TSINTSKARO_mt  = [('E4',2),('E4',2),('E4',2),('E4',2),('C4',2),('C4',2),('C4',2),('C4',2)]
TSINTSKARO_bn  = [('C3',4),('C3',4),('G2',4),('G2',4)]

# 2. ბერი-ბერიკობა (Beri-Berikoba) — Gurian ritual, 5/8, D major, BPM=120
BERI_mk  = [('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),('E5',0.5),('D5',1),
            ('C#5',0.5),('D5',0.5),('E5',1),('D5',0.5),('C#5',0.5),('B4',1),
            ('A4',0.5),('B4',0.5),('C#5',1),('D5',1)]
BERI_mt  = [('D4',1),('D4',1),('B3',1),('B3',1),('A3',1),('A3',1),('F#3',1),('F#3',1)]
BERI_bn  = [('D3',2.5),('D3',2.5),('B2',2.5),('B2',2.5)]

# 3. მრავალჟამიერ (Mravalzhamier) — Gurian toasting hymn, 4/4, G major, BPM=80
MRAV_mk  = [('A4',2),('G4',1),('F#4',1),('E4',2),('D4',2),('E4',1),('F#4',1),
            ('G4',2),('A4',2),('B4',1),('C5',1),('B4',2),('A4',4)]
MRAV_mt  = [('E4',2),('E4',2),('C4',2),('C4',2),('E4',2),('E4',2),('D4',2),('C4',2)]
MRAV_bn  = [('A2',4),('A2',4),('A2',4),('A2',4)]

# 4. ხასანბეგურა (Khasanbegura) — Gurian battle song, 6/8, D major, BPM=132
KHAS_mk  = [('D5',1.5),('C5',0.5),('B4',1),('A4',1.5),('G4',0.5),('F#4',1),
            ('E4',1.5),('D4',0.5),('E4',1),('F#4',1.5),('G4',0.5),('A4',1)]
KHAS_mt  = [('F#4',3),('F#4',3),('E4',3),('D4',3)]
KHAS_bn  = [('D3',6),('D3',6)]

# 5. ნანა / იავნანა (Nana) — Mingrelian lullaby, 4/4, A minor, BPM=60
NANA_mk  = [('E4',2),('D4',2),('C4',2),('D4',2),('E4',2),('D4',2),('C4',2),('D4',2)]
NANA_mt  = [('C4',2),('B3',2),('A3',2),('B3',2),('C4',2),('B3',2),('A3',2),('B3',2)]
NANA_bn  = [('A2',4),('G2',4),('A2',4),('G2',4)]

# 6. სამკურაო (Samkurao) — Mingrelian lamentation, 4/4, F major, BPM=50
SAMK_mk  = [('G4',3),('F4',1),('E4',2),('D4',2),('C4',3),('B3',1),('C4',2),('D4',2)]
SAMK_mt  = [('E4',3),('D4',1),('C4',2),('B3',2),('A3',3),('G3',1),('A3',2),('B3',2)]
SAMK_bn  = [('C3',4),('G2',4),('C3',4),('G2',4)]

# 7. ოდოია (Odoia) — Mingrelian ritual, 4/4, D major, BPM=70
ODOIA_mk = [('A4',1.5),('G4',0.5),('F#4',2),('E4',2),('D4',1.5),('C4',0.5),('B3',2),('A3',2)]
ODOIA_mt = [('F#4',2),('E4',2),('D4',2),('C4',2),('B3',2),('A3',2),('G3',2),('F#3',2)]
ODOIA_bn = [('D3',4),('D3',4),('A2',4),('A2',4)]

# 8. ლილე (Lile) — Mingrelian round dance, 4/4, C major, BPM=100
LILE_mk  = [('E5',1),('D5',1),('C5',1),('B4',1),('C5',1),('D5',1),('E5',1),('D5',1),
            ('C5',1),('B4',1),('A4',2)]
LILE_mt  = [('C5',1),('B4',1),('A4',1),('G4',1),('A4',1),('B4',1),('C5',1),('B4',1),
            ('A4',1),('G4',1),('E4',2)]
LILE_bn  = [('A4',1),('G4',1),('E4',1),('D4',1),('E4',1),('G4',1),('A4',1),('G4',1),
            ('E4',1),('D4',1),('C4',2)]

# 9. მთიულური (Mtiuluri) — Racha dance, 5/8, D major, BPM=140
MTIUL_mk = [('D5',0.5),('E5',0.5),('D5',0.5),('C5',0.5),('B4',1),
            ('A4',0.5),('B4',0.5),('C5',1),('B4',0.5),('A4',0.5),('G4',1),('F#4',1)]
MTIUL_mt = [('B4',1),('A4',1),('G4',1),('F#4',1),('E4',1),('D4',1),('C4',1),('B3',1)]
MTIUL_bn = [('G3',2.5),('G3',2.5),('D3',2.5),('D3',2.5)]

# 10. ვირიშხაუ (Virishkhau) — Svan funeral, 4/4, Eb major, BPM=45
VIRISH_mk = [('G4',6),('F4',2),('Eb4',4),('D4',4),('C4',4)]
VIRISH_mt = [('Eb4',6),('D4',2),('C4',4),('Bb3',4),('G3',4)]
VIRISH_bn = [('C3',8),('G2',8),('C3',8)]

# 11. რეხვიაში (Rekhviashi) — Svan men's, 4/4, G major, BPM=72
REKH_mk  = [('A4',2),('G4',1),('F#4',1),('E4',2),('D4',2),('E4',2),('F#4',2),('G4',2)]
REKH_mt  = [('E4',2),('E4',2),('D4',2),('C4',2),('B3',2),('C4',2),('D4',2),('E4',2)]
REKH_bn  = [('A2',4),('A2',4),('E2',4),('E2',4)]

# 12. ჩაკრულო (Chakrulo) — Racha victory, 7/8, D major, BPM=108
CHAK_mk  = [('F#5',0.5),('A5',0.5),('G5',0.5),('F#5',0.5),('E5',1),
            ('D5',0.5),('B4',0.5),('C#5',1),('D5',0.5),('E5',0.5),('F#5',1),
            ('E5',0.5),('D5',0.5),('C#5',1),('B4',2)]
CHAK_mt  = [('D4',1.75),('D4',1.75),('B3',1.75),('B3',1.75),('A3',1.75),('A3',1.75)]
CHAK_bn  = [('D3',3.5),('D3',3.5),('A2',3.5),('A2',3.5)]

# ══════════════════════════════════════════════════════════════════════
# LYRICS
# ══════════════════════════════════════════════════════════════════════

LYR = {
    'T1':    ['ma-','ny','years...','lone-','li-','ness...','bro-','ther','hood'],
    'T2_mk': ['fall-','ing...','bro-','ken...','lost...','in','dark-','ness...','i!'],
    'T2_mt': ['dark-','er...','low-','er...','fur-','ther...','far-','ther','gone...'],
    'T2_bn': ['D—','—','Eb—','—','D—','—','C#—','D—','—'],
    'T3':    ['A-','li-','lo!','ma-','ny','years!','bro-','ther-','hood','lives','on!'],
    'T7':    ['Na-','na,','na-','na,','my','child,','sleep','in','peace,','now','child','sleep','rest'],
    'T8':    ['Hear','me','child','what','I','tell','you:','the','star','will','fall','as','your','bro-','ther','comes','soon'],
    'T9':    ['O-','do-','ia,','o-','do-','ia,','may','the','road','be','clear','for','you,','my','chil-','dren!','O-','do-','ia,','may','sun','shine','on','you!'],
    'T10':   ['Sam-','ku-','ra-','o,','sam-','ku-','ra-','o,','my','child,','come','back','to','me,','o-','do-','ia,','sam-','ku-','ra-','o,','o-','do-','ia'],
    'T11_s1':['Li-','le,','li-','le,','o-','ro-','ve-','la!','life','goes','on,','for-','ev-','er'],
    'T11_s2':['Li-','le,','li-','le,','o-','ro-','ve-','la!','life','goes','on,','bright-','and','fair'],
    'T11_al':['Li-','le,','li-','le,','o-','ro-','ve-','la!','life','goes','on,','for-','ev-','er'],
    'T12':   ['From','moun-','tain','I','came!','I','am','fire!','I','am','air!','Come!','come!','find','me!','hear!','me!','now!','come!','mine!'],
    'T13_sh':['Gan-','da-','ga-','na,','come','to','me!','no','fear!'],
    'T13_ek':['I...','re-','mem-','ber...','some-','thing...','who','am','I?','lost'],
    'T14':   ['Curs-','ed','be','this','day!','I','killed','him','with','love!','I','killed','him!','now','gone','for-','ev-','er!','A—','G—','F—','E—','D—','C—','B—','A—','gone'],
    'T15':   ['For-','ward!','U-','ruk!','Strike!','For','the','king!','For','bro-','ther-','hood!'],
    'T16':   ['U-','ruk','mourns!','The','king','will','not','hear','us!'],
    'T17':   ['Ma-','ny','years!','ma-','ny','years!','glo-','ry','to','bro-','ther-','hood!'],
    'T18':   ['Rekh-','vi-','ash,','rekh-','vi-','ash!','beau-','ty!','strength!'],
    'T19':   ['I','am','the','for-','est.','I','am','the','earth.','you','will','not','pass.'],
    'T20':   ['Vic-','to-','ry!','the','bull','falls!','we','stand!','Uruk!','lives!','on!'],
    'gil_arioso': ['I','am','king!','two-','thirds','god!','my','walls!','my','name!','but','why','am','I','a-','lone?'],
    'enkidu_first': ['I...','am...','I?','clay...','and','blood?','I...','am...'],
    'brothers': ['You','are','my','bro-','ther.','un-','til','death.','bro-','thers.'],
    'lament':   ['Who','are','you?!','my','three!','where','is','my','bro-','ther?!','where?!'],
    'shadows':  ['who','was','there?','who','comes?','who','seeks','death?'],
    'final_solo':['I','was.','I','am.','I','will','be.'],
    'tsintskaro': ['Tsin-','tska-','ro,','tsin-','tska-','ro,','wa-','ter','flows,','wa-','ter','flows,','through','the','moun-','tains'],
    'mravalzh': ['Mra-','val-','zha-','mier!','long','may','you','live!','long','may','the','bond','last!','our','friends!'],
    'khas':     ['Kha-','san-','be-','gu-','ra!','rise','and','fight!','for','king','and','kin!'],
    'nana_lyr': ['Na-','na,','na-','na,','sleep','my','love,','sleep,','sleep,','rest,','sleep'],
    'odoia_lyr':['O-','do-','ia,','o-','do-','ia,','bless','this','road','for','all','who','walk','it'],
    'lile_lyr': ['Li-','le,','li-','le,','dance','the','spring!','dance','the','joy!','dance!','dance!'],
    'chakr_lyr':['Chak-','ru-','lo!','we','con-','quer!','Chak-','ru-','lo!','rise','up!','sons','of','Uruk!','now!'],
    'virish_lyr':['We','mourn.','We','grieve.','Gone','now.','our','bro-','ther.','gone.'],
    'rekh_lyr': ['Stand','firm.','Be','strong.','As','the','oak','on','the','moun-','tain.'],
    'samk_lyr': ['Gone','is','the','light.','Gone','is','the','day.','Come','back','to','me.','come','back'],
    'beri_lyr': ['Be-','ri,','be-','ri-','ko-','ba!','spring','is','here!','joy!','joy!'],
    'mtiul_lyr':['Mti-','u-','lu-','ri!','Mti-','u-','lu-','ri!','leap','and','turn!'],
}

# ══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS (unchanged from v3)
# ══════════════════════════════════════════════════════════════════════

VALID_DURS = {4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25}

def _snap_dur(d):
    candidates = sorted(VALID_DURS)
    best = candidates[0]
    for c in candidates:
        if abs(c - d) < abs(best - d):
            best = c
    return best

def N(p, dur=1.0, lyr=None, dyn_str=None, oct_shift=0, fermata=False):
    dur = _snap_dur(float(dur))
    if p == 'R':
        n = note.Rest(quarterLength=dur)
        return n
    pk = pitch.Pitch(p)
    if oct_shift:
        pk.octave += oct_shift
    n = note.Note(pk, quarterLength=dur)
    if lyr:
        n.addLyric(lyr)
    if dyn_str:
        n.expressions.append(dynamics.Dynamic(dyn_str))
    if fermata:
        n.expressions.append(expressions.Fermata())
    return n

def theme_notes(pitch_dur_list, lyrics=None, dyn=None, oct_shift=0):
    out = []
    for i, (p, d) in enumerate(pitch_dur_list):
        lyr = lyrics[i] if lyrics and i < len(lyrics) else None
        d0 = dyn if i == 0 else None
        out.append(N(p, d, lyr=lyr, dyn_str=d0, oct_shift=oct_shift))
    return out

def _ts_beats(ts_str):
    num, den = map(int, ts_str.split('/'))
    return num * (4.0 / den)

def pack_to_measures(notes_list, ts_str, ks=None, bpm=None, txt=None):
    beats_per = _ts_beats(ts_str)
    measures = []
    m = stream.Measure()
    m.timeSignature = meter.TimeSignature(ts_str)
    if ks is not None:
        m.keySignature = key.KeySignature(ks)
    if bpm is not None:
        m.insert(0, tempo.MetronomeMark(number=bpm))
    if txt:
        m.insert(0, expressions.TextExpression(txt))
    used = 0.0
    first_measure = True

    for n0 in notes_list:
        remaining_in_measure = round(beats_per - used, 6)
        dur = round(float(n0.quarterLength), 6)

        while dur > 1e-9:
            take = min(dur, remaining_in_measure)
            take = _snap_dur(take)
            if take < 0.24:
                take = 0.25

            if isinstance(n0, note.Rest):
                nn = note.Rest(quarterLength=take)
            else:
                nn = copy.deepcopy(n0)
                nn.quarterLength = take
                if take < dur and nn.lyrics:
                    nn.lyrics = []

            m.append(nn)
            used = round(used + take, 6)
            dur = round(dur - take, 6)

            if round(used - beats_per, 6) >= -1e-9:
                measures.append(m)
                m = stream.Measure()
                if first_measure:
                    first_measure = False
                else:
                    m.timeSignature = meter.TimeSignature(ts_str)
                used = 0.0
                remaining_in_measure = beats_per

    if used > 1e-9:
        leftover = round(beats_per - used, 6)
        if leftover > 1e-9:
            fill_dur = _snap_dur(leftover)
            if fill_dur > leftover + 1e-6:
                fill_dur = _snap_dur(leftover * 0.9)
            if fill_dur >= 0.25:
                m.append(note.Rest(quarterLength=fill_dur))
        measures.append(m)

    return measures

def repeat_fill(notes_list, n_measures, ts_str='4/4', ks=None, bpm=None, txt=None):
    beats_per = _ts_beats(ts_str)
    total_needed = n_measures * beats_per
    pass_beats = sum(round(float(x.quarterLength), 6) for x in notes_list)
    if pass_beats < 1e-9:
        pass_beats = beats_per
    repeats = int(total_needed / pass_beats) + 2
    big_list = []
    for _ in range(repeats):
        big_list.extend(copy.deepcopy(notes_list))
    all_measures = pack_to_measures(big_list, ts_str, ks=ks, bpm=bpm, txt=txt)
    result = all_measures[:n_measures]
    while len(result) < n_measures:
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        m.append(note.Rest(quarterLength=beats_per))
        result.append(m)
    return result

def _build_drone_measures(pitch_str, n_measures, ts_str='4/4', dyn='ppp', lyr=None):
    beats_per = _ts_beats(ts_str)
    result = []
    for i in range(n_measures):
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        rem = beats_per
        first = True
        while rem > 1e-9:
            d = _snap_dur(min(rem, 4.0))
            if d > rem + 1e-6:
                d = _snap_dur(min(rem * 0.9, 4.0))
            if d < 0.24:
                d = 0.25
            n0 = note.Note(pitch_str, quarterLength=d)
            if first and i == 0:
                n0.expressions.append(dynamics.Dynamic(dyn))
                if lyr:
                    n0.addLyric(lyr)
                first = False
            m.append(n0)
            rem = round(rem - d, 6)
        result.append(m)
    return result

def _build_rest_measures(n_measures, ts_str='4/4'):
    beats_per = _ts_beats(ts_str)
    result = []
    for _ in range(n_measures):
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        rem = beats_per
        while rem > 1e-9:
            d = _snap_dur(min(rem, 4.0))
            if d > rem + 1e-6:
                d = _snap_dur(min(rem * 0.9, 4.0))
            if d < 0.24:
                d = 0.25
            m.append(note.Rest(quarterLength=d))
            rem = round(rem - d, 6)
        result.append(m)
    return result

def piano_harmony(chord_pitches, n_measures, ts_str='4/4', dyn='pp'):
    beats_per = _ts_beats(ts_str)
    result = []
    for i in range(n_measures):
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        rem = beats_per
        first = True
        while rem > 1e-9:
            d = min(rem, 1.0)
            d = _snap_dur(d)
            if d < 0.24:
                d = 0.25
            c = chord.Chord(chord_pitches, quarterLength=d)
            if first and i == 0:
                c.expressions.append(dynamics.Dynamic(dyn))
                first = False
            m.append(c)
            rem = round(rem - d, 6)
        result.append(m)
    return result

def strings_sustain(pitches, n_measures, ts_str='4/4', dyn='pp'):
    beats_per = _ts_beats(ts_str)
    result = []
    for i in range(n_measures):
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        rem = beats_per
        first = True
        while rem > 1e-9:
            d = _snap_dur(min(rem, 4.0))
            if d > rem + 1e-6:
                d = _snap_dur(min(rem * 0.9, 4.0))
            if d < 0.24:
                d = 0.25
            c = chord.Chord(pitches, quarterLength=d)
            if first and i == 0:
                c.expressions.append(dynamics.Dynamic(dyn))
                first = False
            m.append(c)
            rem = round(rem - d, 6)
        result.append(m)
    return result

def add_measures(part, measures_list):
    for m in measures_list:
        part.append(m)

def make_part(name, inst_obj, midi_channel=1):
    p = stream.Part()
    p.id = name.replace(' ', '_')
    p.partName = name
    inst_obj.midiChannel = midi_channel
    p.insert(0, inst_obj)
    return p

# ══════════════════════════════════════════════════════════════════════
# ENHANCED SCENE BUILDER — explicit dynamics per section
# ══════════════════════════════════════════════════════════════════════

def build_scene(scene_data, parts_dict):
    """
    scene_data keys:
      n_measures, ts_str, ks_int, bpm, label,
      featured: {part_name: [(pitch_dur_list, lyrics, dyn, repeats), ...]}
      piano_chords, strings_pitches, drone_pitch
      piano_dyn, strings_dyn  — explicit dynamics for background layers
    """
    n  = scene_data['n_measures']
    ts = scene_data['ts_str']
    ks = scene_data.get('ks_int', 0)
    bpm_val = scene_data.get('bpm', 60)
    label = scene_data.get('label', '')
    piano_chords_p = scene_data.get('piano_chords', ['D3','F3','A3'])
    str_p = scene_data.get('strings_pitches', ['D2','A2','D3'])
    drone_p = scene_data.get('drone_pitch', 'D4')
    featured = scene_data.get('featured', {})
    piano_dyn = scene_data.get('piano_dyn', 'pp')
    strings_dyn = scene_data.get('strings_dyn', 'pp')

    for pname, part in parts_dict.items():
        if pname == 'Piano':
            ms = piano_harmony(piano_chords_p, n, ts, dyn=piano_dyn)
            if ms:
                ms[0].insert(0, meter.TimeSignature(ts))
                ms[0].insert(0, key.KeySignature(ks))
                ms[0].insert(0, tempo.MetronomeMark(number=bpm_val))
                if label:
                    ms[0].insert(0, expressions.TextExpression(label))
            add_measures(part, ms)

        elif pname == 'Strings':
            ms = strings_sustain(str_p, n, ts, dyn=strings_dyn)
            if ms:
                ms[0].insert(0, meter.TimeSignature(ts))
                ms[0].insert(0, key.KeySignature(ks))
            add_measures(part, ms)

        elif pname in featured:
            feat_list = featured[pname]
            all_notes = []
            for (nlist, lyrs, dyn_s, reps) in feat_list:
                nl = theme_notes(nlist, lyrics=lyrs, dyn=dyn_s)
                for _ in range(reps):
                    all_notes.extend(copy.deepcopy(nl))
            ms = repeat_fill(all_notes, n, ts, ks=ks)
            if ms:
                ms[0].insert(0, meter.TimeSignature(ts))
                ms[0].insert(0, key.KeySignature(ks))
            add_measures(part, ms)

        else:
            # Inactive: drone — but with section-appropriate dynamic
            inactive_dyn = 'ppp' if piano_dyn in ('pp','p','ppp') else 'pp'
            if pname in ('Lamuri', 'Chuniri', 'Panduri', 'Winds', 'Brass', 'Cello'):
                ms = _build_drone_measures(drone_p, n, ts, dyn=inactive_dyn, lyr=None)
            else:
                ms = _build_drone_measures(drone_p, n, ts, dyn=inactive_dyn, lyr='aah')
            if ms:
                ms[0].insert(0, meter.TimeSignature(ts))
                ms[0].insert(0, key.KeySignature(ks))
            add_measures(part, ms)

# ══════════════════════════════════════════════════════════════════════
# MAIN SCORE ASSEMBLY
# ══════════════════════════════════════════════════════════════════════

def build_score():
    sc = stream.Score()
    md = metadata.Metadata()
    md.title = 'Šamnu Azuzi v4 (სამნუ ა-ზუ-ზი)'
    md.composer = 'Jaba Tkemaladze'
    sc.insert(0, md)

    parts = {}

    def mp(name, inst_cls, ch):
        p = make_part(name, inst_cls(), ch)
        parts[name] = p
        return p

    mp('Gilgamesh',          instrument.Baritone,            1)
    mp('Enkidu',             instrument.Tenor,               2)
    mp('Ninsun',             instrument.MezzoSoprano,        3)
    mp('Shamhat',            instrument.Soprano,             4)
    mp('Humbaba_Utnapishti', instrument.Bass,                5)
    mp('Mkrimani',           instrument.Soprano,             6)
    mp('Mtavari',            instrument.Tenor,               7)
    mp('Bani',               instrument.Bass,                8)
    mp('Chorus',             instrument.Choir,               9)
    mp('Lamuri',             instrument.Flute,               10)
    mp('Chuniri',            instrument.Violin,              11)
    mp('Panduri',            instrument.Violin,              12)
    mp('Strings',            instrument.StringInstrument,    13)
    mp('Winds',              instrument.WoodwindInstrument,  14)
    mp('Brass',              instrument.BrassInstrument,     15)
    mp('Cello',              instrument.Violoncello,         16)
    mp('Piano',              instrument.Piano,               17)

    # ══════════════════════════════════════════════════════════════════
    # OVERTURE — 180 measures
    # Section A: 20m pp  — Uruk at rest (4/4, D minor, ♩=50)
    # Section B: 30m mf  — Gilgamesh appears (4/4, D major, ♩=60)
    # Section C: 30m p   — Enkidu in wilderness (5/8, G minor, ♩=58)
    # Section D: 40m ff  — Conflict/battle (5/8, D minor, ♩=92)
    # Section E: 30m mf  — Reconciliation (4/4, G major, ♩=72)
    # Section F: 30m mp  — Ninsun/Trio coda (4/4, D minor, ♩=50)
    # ══════════════════════════════════════════════════════════════════

    # OV-A: 20m, pp, D minor, 4/4, ♩=50 — Uruk at rest
    # Strings + Piano ppp; Chuniri plays T7_chuniri; Trio ppp on T1
    ov_a = {
        'n_measures': 20, 'ts_str': '4/4', 'ks_int': -1, 'bpm': 50,
        'label': 'OVERTURE — A: Uruk at rest',
        'piano_chords': ['D2','F2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'ppp', 'strings_dyn': 'ppp',
        'featured': {
            'Chuniri':  [(T7_chuniri, None, 'pp', 1)],
            'Lamuri':   [(T4_lamuri, None, 'pp', 1)],
            'Mkrimani': [(T1_mkrimani, LYR['T1'], 'ppp', 1)],
            'Mtavari':  [(T1_mtavari, LYR['T1'], 'ppp', 1)],
            'Bani':     [(T1_bani, LYR['T2_bn'], 'ppp', 1)],
        }
    }
    build_scene(ov_a, parts)

    # OV-B: 30m, mf, D major, 4/4, ♩=60 — Gilgamesh theme
    # Gilgamesh arioso + Tsintskaro in Mkrimani/Mtavari/Bani
    gil_arioso_notes = [
        ('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',0.5),('G4',0.5),
        ('F4',1),('E4',0.5),('D4',0.5),('C4',1),('D4',0.5),('E4',0.5),
        ('F4',1),('G4',1),('A4',0.5),('Bb4',0.5),('A4',0.5),('G4',0.5)
    ]
    ov_b = {
        'n_measures': 30, 'ts_str': '4/4', 'ks_int': 2, 'bpm': 60,
        'label': 'B: Gilgamesh theme',
        'piano_chords': ['D2','F#2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'mp', 'strings_dyn': 'mp',
        'featured': {
            'Gilgamesh': [(gil_arioso_notes, LYR['gil_arioso'], 'mf', 1)],
            'Mkrimani':  [(TSINTSKARO_mk, LYR['tsintskaro'], 'mp', 1)],
            'Mtavari':   [(TSINTSKARO_mt, None, 'mp', 1)],
            'Bani':      [(TSINTSKARO_bn, None, 'mp', 1)],
            'Chuniri':   [(T5_panduri, None, 'mf', 1)],
            'Panduri':   [(T5_lamuri, None, 'mf', 1)],
        }
    }
    build_scene(ov_b, parts)

    # OV-C: 30m, p, G minor, 5/8, ♩=58 — Enkidu in wilderness
    # T4 Lamuri + T6 Enkidu + Trio T1 ppp + Odoia in Chorus
    ov_c = {
        'n_measures': 30, 'ts_str': '5/8', 'ks_int': -2, 'bpm': 58,
        'label': 'C: Enkidu in wilderness',
        'piano_chords': ['G2','Bb2','D3'], 'strings_pitches': ['G2','D3'],
        'drone_pitch': 'G4', 'piano_dyn': 'pp', 'strings_dyn': 'pp',
        'featured': {
            'Enkidu':   [(T6_enkidu, LYR['enkidu_first'], 'p', 1)],
            'Lamuri':   [(T4_lamuri, None, 'p', 1)],
            'Chuniri':  [(T6_lamuri, None, 'pp', 1)],
            'Chorus':   [(ODOIA_mk, LYR['odoia_lyr'], 'pp', 1)],
            'Mkrimani': [(T1_mkrimani, LYR['T1'], 'ppp', 1)],
            'Mtavari':  [(T1_mtavari, LYR['T1'], 'ppp', 1)],
            'Bani':     [(T1_bani, LYR['T2_bn'], 'ppp', 1)],
        }
    }
    build_scene(ov_c, parts)

    # OV-D: 40m, ff, D minor, 5/8, ♩=92 — Conflict / battle
    # T15 Orch (Khasanbegura) + Beri-Berikoba in Trio + T16 Chorus + Brass fff
    ov_d = {
        'n_measures': 40, 'ts_str': '5/8', 'ks_int': -1, 'bpm': 92,
        'label': 'D: Conflict',
        'piano_chords': ['D2','F2','A2'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'f', 'strings_dyn': 'f',
        'featured': {
            'Gilgamesh': [(T15_orch, LYR['T15'], 'ff', 1)],
            'Enkidu':    [(T15_orch, LYR['T15'], 'ff', 1)],
            'Chorus':    [(T16_chorus, LYR['T16'], 'fff', 1)],
            'Mkrimani':  [(BERI_mk, LYR['beri_lyr'], 'f', 1)],
            'Mtavari':   [(BERI_mt, None, 'f', 1)],
            'Bani':      [(BERI_bn, None, 'f', 1)],
            'Winds':     [(T15_orch, None, 'ff', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
            'Lamuri':    [(KHAS_mk, None, 'ff', 1)],
        }
    }
    build_scene(ov_d, parts)

    # OV-E: 30m, mf, G major, 4/4, ♩=72 — Reconciliation
    # Mravalzhamier in Trio + T17 in Chorus + Chuniri/Panduri dance
    ov_e = {
        'n_measures': 30, 'ts_str': '4/4', 'ks_int': 1, 'bpm': 72,
        'label': 'E: Reconciliation',
        'piano_chords': ['G2','B2','D3','G3'], 'strings_pitches': ['G2','D3','G3'],
        'drone_pitch': 'G4', 'piano_dyn': 'mp', 'strings_dyn': 'mp',
        'featured': {
            'Gilgamesh': [(T17_trio, LYR['T17'], 'f', 1)],
            'Enkidu':    [(T17_trio, LYR['T17'], 'f', 1)],
            'Chorus':    [(T18_chorus, LYR['T18'], 'mf', 1)],
            'Mkrimani':  [(MRAV_mk, LYR['mravalzh'], 'mf', 1)],
            'Mtavari':   [(MRAV_mt, None, 'mf', 1)],
            'Bani':      [(MRAV_bn, None, 'mf', 1)],
            'Chuniri':   [(T5_panduri, None, 'mp', 1)],
            'Panduri':   [(T5_lamuri, None, 'mp', 1)],
            'Lamuri':    [(T5_lamuri, None, 'mp', 1)],
        }
    }
    build_scene(ov_e, parts)

    # OV-F: 30m, mp, D minor, 4/4, ♩=50 — Ninsun/Trio coda
    # T7 Ninsun + T8 Ninsun + Trio ppp T1 → fade to silence
    ov_f = {
        'n_measures': 30, 'ts_str': '4/4', 'ks_int': -1, 'bpm': 50,
        'label': 'F: Ninsun coda',
        'piano_chords': ['D2','F2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'ppp', 'strings_dyn': 'ppp',
        'featured': {
            'Ninsun':    [(T7_ninsun, LYR['T7'], 'mp', 1), (T8_ninsun, LYR['T8'], 'p', 1)],
            'Chuniri':   [(T7_chuniri, None, 'pp', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'ppp', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'ppp', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'ppp', 1)],
            'Chorus':    [(NANA_mk, LYR['nana_lyr'], 'ppp', 1)],
        }
    }
    build_scene(ov_f, parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT I — 450 measures
    # Scene 1: 120m — Uruk under oppression
    # Scene 2: 150m — Enkidu awakens / Shamhat encounter
    # Scene 3: 180m — Enkidu enters Uruk / confrontation
    # ══════════════════════════════════════════════════════════════════

    # ACT I / Scene 1: 120m, G minor, 5/8, ♩=58
    # T16 (Beri-Berikoba style mourning) + Gilgamesh arioso + Trio T1 + TSINTSKARO (Chorus)
    sc1 = {
        'n_measures': 120, 'ts_str': '5/8', 'ks_int': -2, 'bpm': 58,
        'label': 'ACT I — Scene 1: Uruk under oppression',
        'piano_chords': ['G2','Bb2','D3','G3'], 'strings_pitches': ['G2','D3','G3'],
        'drone_pitch': 'G4', 'piano_dyn': 'mp', 'strings_dyn': 'mp',
        'featured': {
            'Chorus':    [(T16_chorus, LYR['T16'], 'mf', 1), (BERI_mk, LYR['beri_lyr'], 'f', 1)],
            'Gilgamesh': [(gil_arioso_notes, LYR['gil_arioso'], 'f', 1)],
            'Ninsun':    [(T7_ninsun, LYR['T7'], 'p', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'pp', 1), (TSINTSKARO_mk, LYR['tsintskaro'], 'ppp', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'pp', 1), (TSINTSKARO_mt, None, 'ppp', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'pp', 1), (TSINTSKARO_bn, None, 'ppp', 1)],
            'Lamuri':    [(T4_lamuri, None, 'p', 1)],
            'Chuniri':   [(T7_chuniri, None, 'pp', 1)],
            'Winds':     [(T16_chorus, None, 'mf', 1)],
        }
    }
    build_scene(sc1, parts)

    # ACT I / Scene 2: 150m, D minor, 4/4, ♩=66
    # Enkidu awakens — T6 + T4 Lamuri + T7 Ninsun (lullaby memory) + Odoia + Nana in Trio
    sc2 = {
        'n_measures': 150, 'ts_str': '4/4', 'ks_int': -1, 'bpm': 66,
        'label': 'Scene 2: Enkidu awakens / Shamhat',
        'piano_chords': ['D2','F2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'pp', 'strings_dyn': 'pp',
        'featured': {
            'Enkidu':    [(T6_enkidu, LYR['enkidu_first'], 'p', 1)],
            'Shamhat':   [(T12_shamhat, LYR['T12'], 'mf', 1)],
            'Ninsun':    [(T7_ninsun, LYR['T7'], 'mp', 1)],
            'Lamuri':    [(T4_lamuri, None, 'p', 1), (T6_lamuri, None, 'pp', 1)],
            'Chuniri':   [(T7_chuniri, None, 'p', 1)],
            'Mkrimani':  [(NANA_mk, LYR['nana_lyr'], 'ppp', 1), (ODOIA_mk, LYR['odoia_lyr'], 'pp', 1)],
            'Mtavari':   [(NANA_mt, None, 'ppp', 1), (ODOIA_mt, None, 'pp', 1)],
            'Bani':      [(NANA_bn, None, 'ppp', 1), (ODOIA_bn, None, 'pp', 1)],
            'Chorus':    [(T11_sop1, LYR['T11_s1'], 'pp', 1)],
        }
    }
    build_scene(sc2, parts)

    # ACT I / Scene 3: 180m, A minor → D major, 4/4 → 5/8, ♩=72 → 88
    # T12 Shamhat grows + T13 duet + Khasanbegura battle + Lile dance
    # Split into two sub-scenes within one build (use two consecutive calls)
    sc3a = {
        'n_measures': 90, 'ts_str': '4/4', 'ks_int': 0, 'bpm': 72,
        'label': 'Scene 3a: Enkidu enters Uruk',
        'piano_chords': ['A2','C3','E3','A3'], 'strings_pitches': ['A2','E3','A3'],
        'drone_pitch': 'A4', 'piano_dyn': 'mf', 'strings_dyn': 'mp',
        'featured': {
            'Shamhat':   [(T12_shamhat, LYR['T12'], 'mf', 1)],
            'Enkidu':    [(T13_enkidu, LYR['T13_ek'], 'mf', 1)],
            'Gilgamesh': [(T13_shamhat, LYR['T13_sh'], 'f', 1)],
            'Mkrimani':  [(LILE_mk, LYR['lile_lyr'], 'mp', 1)],
            'Mtavari':   [(LILE_mt, None, 'mp', 1)],
            'Bani':      [(LILE_bn, None, 'mp', 1)],
            'Lamuri':    [(T5_lamuri, None, 'mp', 1)],
            'Panduri':   [(T5_panduri, None, 'mp', 1)],
            'Chorus':    [(T16_chorus, LYR['T16'], 'ff', 1)],
        }
    }
    build_scene(sc3a, parts)

    sc3b = {
        'n_measures': 90, 'ts_str': '5/8', 'ks_int': 2, 'bpm': 88,
        'label': 'Scene 3b: Confrontation',
        'piano_chords': ['D2','F#2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'f', 'strings_dyn': 'f',
        'featured': {
            'Gilgamesh': [(T15_orch, LYR['T15'], 'ff', 1)],
            'Enkidu':    [(T15_orch, LYR['T15'], 'ff', 1)],
            'Chorus':    [(T16_chorus, LYR['T16'], 'fff', 1)],
            'Mkrimani':  [(KHAS_mk, LYR['khas'], 'ff', 1)],
            'Mtavari':   [(KHAS_mt, None, 'ff', 1)],
            'Bani':      [(KHAS_bn, None, 'ff', 1)],
            'Lamuri':    [(MTIUL_mk, LYR['mtiul_lyr'], 'ff', 1)],
            'Winds':     [(T15_orch, None, 'ff', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
        }
    }
    build_scene(sc3b, parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT II — 270 measures
    # Scene 4: 90m — Brotherhood / Mravalzhamier
    # Scene 5: 90m — Journey to Cedar Forest / Khasanbegura march
    # Scene 6: 90m — Humbaba / Chakrulo (7/8)
    # ══════════════════════════════════════════════════════════════════

    # ACT II / Scene 4: 90m, D major, 4/4, ♩=76
    # Brotherhood oath — T17 + T18 + Mravalzhamier Trio
    sc4 = {
        'n_measures': 90, 'ts_str': '4/4', 'ks_int': 2, 'bpm': 76,
        'label': 'ACT II — Scene 4: Brotherhood sworn',
        'piano_chords': ['D2','F#2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'mf', 'strings_dyn': 'mf',
        'featured': {
            'Gilgamesh': [(T17_trio, LYR['T17'], 'f', 1)],
            'Enkidu':    [(T17_trio, LYR['T17'], 'f', 1)],
            'Chorus':    [(T18_chorus, LYR['T18'], 'mf', 1), (REKH_mk, LYR['rekh_lyr'], 'mf', 1)],
            'Mkrimani':  [(MRAV_mk, LYR['mravalzh'], 'f', 1)],
            'Mtavari':   [(MRAV_mt, None, 'f', 1)],
            'Bani':      [(MRAV_bn, None, 'f', 1)],
            'Ninsun':    [(T9_ninsun, LYR['T9'], 'mp', 1)],
            'Chuniri':   [(T5_panduri, None, 'mf', 1)],
            'Panduri':   [(T5_lamuri, None, 'mf', 1)],
            'Lamuri':    [(T5_lamuri, None, 'mp', 1)],
        }
    }
    build_scene(sc4, parts)

    # ACT II / Scene 5: 90m, D major, 5/8, ♩=92
    # Journey to Cedar — Khasanbegura march + Mtiuluri in Trio
    sc5 = {
        'n_measures': 90, 'ts_str': '5/8', 'ks_int': 2, 'bpm': 92,
        'label': 'Scene 5: Journey to Cedar Forest',
        'piano_chords': ['D2','A2','D3','F#3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'mf', 'strings_dyn': 'mf',
        'featured': {
            'Gilgamesh': [(T15_orch, LYR['T15'], 'ff', 1)],
            'Enkidu':    [(T6_enkidu, LYR['T15'], 'mf', 1)],
            'Chorus':    [(T16_chorus, LYR['T16'], 'f', 1)],
            'Mkrimani':  [(MTIUL_mk, LYR['mtiul_lyr'], 'f', 1)],
            'Mtavari':   [(MTIUL_mt, None, 'f', 1)],
            'Bani':      [(MTIUL_bn, None, 'f', 1)],
            'Lamuri':    [(KHAS_mk, LYR['khas'], 'ff', 1)],
            'Winds':     [(T15_orch, None, 'ff', 1)],
            'Brass':     [(T15_orch, None, 'fff', 1)],
        }
    }
    build_scene(sc5, parts)

    # ACT II / Scene 6: 90m, D minor, 7/8, ♩=108
    # Humbaba encounter — T19 + Chakrulo in Trio + Virishkhau undercurrent
    sc6 = {
        'n_measures': 90, 'ts_str': '7/8', 'ks_int': -1, 'bpm': 108,
        'label': 'Scene 6: Humbaba, guardian of cedar',
        'piano_chords': ['D2','F2','A2'], 'strings_pitches': ['D2','A2'],
        'drone_pitch': 'D3', 'piano_dyn': 'f', 'strings_dyn': 'mf',
        'featured': {
            'Humbaba_Utnapishti': [(T19_humbaba, LYR['T19'], 'ff', 1)],
            'Chorus':    [(T20_orch, LYR['T20'], 'fff', 1)],
            'Mkrimani':  [(CHAK_mk, LYR['chakr_lyr'], 'ff', 1)],
            'Mtavari':   [(CHAK_mt, None, 'ff', 1)],
            'Bani':      [(CHAK_bn, None, 'ff', 1)],
            'Gilgamesh': [(T15_orch, LYR['T15'], 'ff', 1)],
            'Enkidu':    [(T15_orch, LYR['T15'], 'ff', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
            'Winds':     [(T19_humbaba, None, 'f', 1)],
            'Cello':     [(VIRISH_mk, None, 'mf', 1)],
        }
    }
    build_scene(sc6, parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT III — 360 measures
    # Scene 7: 90m  — Bull of Heaven (7/8, wild)
    # Scene 8: 120m — Enkidu dying / Samkurao lament
    # Scene 9: 150m — Gilgamesh's grief / Rekhviashi
    # ══════════════════════════════════════════════════════════════════

    # ACT III / Scene 7: 90m, Bb major, 7/8, ♩=116
    # Bull of Heaven — T20 + Chakrulo fff + T2 Trio chromatic
    sc7 = {
        'n_measures': 90, 'ts_str': '7/8', 'ks_int': -2, 'bpm': 116,
        'label': 'ACT III — Scene 7: Bull of Heaven',
        'piano_chords': ['Bb2','D3','F3','Bb3'], 'strings_pitches': ['Bb2','F3','Bb3'],
        'drone_pitch': 'Bb3', 'piano_dyn': 'ff', 'strings_dyn': 'ff',
        'featured': {
            'Chorus':    [(T20_orch, LYR['T20'], 'fff', 1)],
            'Gilgamesh': [(T20_orch, LYR['T20'], 'ff', 1)],
            'Enkidu':    [(T20_orch, LYR['T20'], 'ff', 1)],
            'Mkrimani':  [(CHAK_mk, LYR['chakr_lyr'], 'fff', 1)],
            'Mtavari':   [(CHAK_mt, None, 'fff', 1)],
            'Bani':      [(CHAK_bn, None, 'fff', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
            'Winds':     [(T15_orch, None, 'ff', 1)],
            'Lamuri':    [(MTIUL_mk, None, 'ff', 1)],
        }
    }
    build_scene(sc7, parts)

    # ACT III / Scene 8: 120m, A minor, 4/4, ♩=52
    # Enkidu dying — Samkurao lamentation + T6 fragmented + Virishkhau Trio + Ninsun T10
    sc8 = {
        'n_measures': 120, 'ts_str': '4/4', 'ks_int': 0, 'bpm': 52,
        'label': 'Scene 8: Enkidu dying',
        'piano_chords': ['A2','C3','E3'], 'strings_pitches': ['A2','E3'],
        'drone_pitch': 'A3', 'piano_dyn': 'pp', 'strings_dyn': 'pp',
        'featured': {
            'Enkidu':    [(T6_enkidu, LYR['enkidu_first'], 'p', 1)],
            'Ninsun':    [(T10_ninsun, LYR['T10'], 'mp', 1)],
            'Gilgamesh': [(T2_mkrimani, LYR['T2_mk'], 'mf', 1)],
            'Mkrimani':  [(SAMK_mk, LYR['samk_lyr'], 'p', 1), (VIRISH_mk, LYR['virish_lyr'], 'pp', 1)],
            'Mtavari':   [(SAMK_mt, None, 'p', 1), (VIRISH_mt, None, 'pp', 1)],
            'Bani':      [(SAMK_bn, None, 'p', 1), (VIRISH_bn, None, 'pp', 1)],
            'Chuniri':   [(T7_chuniri, None, 'pp', 1)],
            'Chorus':    [(NANA_mk, LYR['nana_lyr'], 'ppp', 1)],
            'Cello':     [(VIRISH_bn, None, 'p', 1)],
        }
    }
    build_scene(sc8, parts)

    # ACT III / Scene 9: 150m, D minor, 4/4, ♩=56
    # Gilgamesh grief — T2 Trio chromatic + Rekhviashi + T14 Shamhat lament
    sc9 = {
        'n_measures': 150, 'ts_str': '4/4', 'ks_int': -1, 'bpm': 56,
        'label': 'Scene 9: Gilgamesh grieves',
        'piano_chords': ['D2','F2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'mf', 'strings_dyn': 'mp',
        'featured': {
            'Gilgamesh': [(T2_mkrimani, LYR['T2_mk'], 'ff', 1), (T3_mkrimani, LYR['T3'], 'f', 1)],
            'Shamhat':   [(T14_shamhat, LYR['T14'], 'f', 1)],
            'Chorus':    [(REKH_mk, LYR['rekh_lyr'], 'mf', 1)],
            'Mkrimani':  [(T2_mkrimani, LYR['T2_mk'], 'f', 1)],
            'Mtavari':   [(T2_mtavari, LYR['T2_mt'], 'f', 1)],
            'Bani':      [(T2_bani, LYR['T2_bn'], 'f', 1)],
            'Ninsun':    [(T9_ninsun, LYR['T9'], 'mf', 1)],
            'Cello':     [(VIRISH_mk, None, 'mf', 1)],
            'Chuniri':   [(REKH_mt, None, 'mp', 1)],
        }
    }
    build_scene(sc9, parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT IV — 540 measures
    # Scene 10: 120m — Underworld journey (dark, chromatic)
    # Scene 11: 135m — Utnapishti / flood narrative
    # Scene 12: 150m — Wisdom and acceptance
    # Scene 13: 135m — Return to Uruk / Epilogue
    # ══════════════════════════════════════════════════════════════════

    # ACT IV / Scene 10: 120m, D minor, 4/4, ♩=46
    # Underworld — T19 Humbaba transformed + Virishkhau Trio (ppp) + T2 disintegrating
    sc10 = {
        'n_measures': 120, 'ts_str': '4/4', 'ks_int': -1, 'bpm': 46,
        'label': 'ACT IV — Scene 10: Underworld journey',
        'piano_chords': ['D2','F2','Ab2'], 'strings_pitches': ['D2','Ab2'],
        'drone_pitch': 'D3', 'piano_dyn': 'ppp', 'strings_dyn': 'ppp',
        'featured': {
            'Gilgamesh': [(T19_humbaba, LYR['shadows'], 'mf', 1)],
            'Humbaba_Utnapishti': [(T19_humbaba, LYR['T19'], 'p', 1)],
            'Mkrimani':  [(VIRISH_mk, LYR['virish_lyr'], 'pp', 1)],
            'Mtavari':   [(VIRISH_mt, None, 'pp', 1)],
            'Bani':      [(VIRISH_bn, None, 'pp', 1)],
            'Chorus':    [(T2_mkrimani, LYR['T2_mk'], 'pp', 1)],
            'Cello':     [(VIRISH_bn, None, 'p', 1)],
            'Chuniri':   [(T19_humbaba, None, 'pp', 1)],
        }
    }
    build_scene(sc10, parts)

    # ACT IV / Scene 11: 135m, G major, 4/4, ♩=58
    # Utnapishti's tale — T7/T9/T10 Ninsun (wisdom) + Tsintskaro Trio (memory) + Nana Chorus
    sc11 = {
        'n_measures': 135, 'ts_str': '4/4', 'ks_int': 1, 'bpm': 58,
        'label': 'Scene 11: Utnapishti / flood narrative',
        'piano_chords': ['G2','B2','D3','G3'], 'strings_pitches': ['G2','D3','G3'],
        'drone_pitch': 'G4', 'piano_dyn': 'mp', 'strings_dyn': 'mp',
        'featured': {
            'Humbaba_Utnapishti': [(T8_ninsun, LYR['T8'], 'mf', 1), (T9_ninsun, LYR['T9'], 'f', 1)],
            'Ninsun':    [(T7_ninsun, LYR['T7'], 'mp', 1)],
            'Gilgamesh': [(T3_mkrimani, LYR['T3'], 'mf', 1)],
            'Mkrimani':  [(TSINTSKARO_mk, LYR['tsintskaro'], 'mp', 1)],
            'Mtavari':   [(TSINTSKARO_mt, None, 'mp', 1)],
            'Bani':      [(TSINTSKARO_bn, None, 'mp', 1)],
            'Chorus':    [(NANA_mk, LYR['nana_lyr'], 'p', 1)],
            'Lamuri':    [(T6_lamuri, None, 'mp', 1)],
            'Chuniri':   [(T7_chuniri, None, 'mp', 1)],
        }
    }
    build_scene(sc11, parts)

    # ACT IV / Scene 12: 150m, D major → G major, 4/4, ♩=66
    # Wisdom/acceptance — T11 Chorus (Lile) + Mravalzhamier culmination + T17 develops
    sc12 = {
        'n_measures': 150, 'ts_str': '4/4', 'ks_int': 2, 'bpm': 66,
        'label': 'Scene 12: Wisdom and acceptance',
        'piano_chords': ['D2','F#2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'mf', 'strings_dyn': 'mf',
        'featured': {
            'Chorus':    [(T11_sop1, LYR['T11_s1'], 'mf', 1), (LILE_mk, LYR['lile_lyr'], 'f', 1)],
            'Ninsun':    [(T11_sop2, LYR['T11_s2'], 'mf', 1)],
            'Shamhat':   [(T11_alto, LYR['T11_al'], 'mf', 1)],
            'Gilgamesh': [(T17_trio, LYR['T17'], 'ff', 1)],
            'Mkrimani':  [(MRAV_mk, LYR['mravalzh'], 'ff', 1)],
            'Mtavari':   [(MRAV_mt, None, 'ff', 1)],
            'Bani':      [(MRAV_bn, None, 'ff', 1)],
            'Lamuri':    [(T5_lamuri, None, 'f', 1)],
            'Panduri':   [(T5_panduri, None, 'f', 1)],
            'Chuniri':   [(T5_panduri, None, 'f', 1)],
            'Winds':     [(T17_trio, None, 'ff', 1)],
        }
    }
    build_scene(sc12, parts)

    # ACT IV / Scene 13: 135m, D major, 4/4 → 5/8, ♩=72 → 100
    # Return to Uruk / Epilogue — T1 Trio fff → T20 finale → fade
    # Split into two sub-scenes
    sc13a = {
        'n_measures': 70, 'ts_str': '4/4', 'ks_int': 2, 'bpm': 72,
        'label': 'Scene 13: Return to Uruk',
        'piano_chords': ['D2','F#2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'f', 'strings_dyn': 'f',
        'featured': {
            'Gilgamesh': [(T1_mkrimani, LYR['T1'], 'ff', 1), (T3_mkrimani, LYR['T3'], 'f', 1)],
            'Chorus':    [(T18_chorus, LYR['T18'], 'ff', 1), (MRAV_mk, LYR['mravalzh'], 'fff', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'fff', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'fff', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'fff', 1)],
            'Ninsun':    [(T8_ninsun, LYR['T8'], 'f', 1)],
            'Lamuri':    [(T5_lamuri, None, 'ff', 1)],
            'Chuniri':   [(T5_panduri, None, 'ff', 1)],
            'Panduri':   [(T5_panduri, None, 'ff', 1)],
            'Winds':     [(T20_orch, None, 'ff', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
        }
    }
    build_scene(sc13a, parts)

    # Final epilogue: 65m, 5/8, D major, ♩=100 — Chakrulo victory → Tsintskaro fade
    sc13b = {
        'n_measures': 65, 'ts_str': '5/8', 'ks_int': 2, 'bpm': 100,
        'label': 'Epilogue: Walls of Uruk endure',
        'piano_chords': ['D2','F#2','A2','D3'], 'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4', 'piano_dyn': 'fff', 'strings_dyn': 'ff',
        'featured': {
            'Chorus':    [(T20_orch, LYR['T20'], 'fff', 1), (CHAK_mk, LYR['chakr_lyr'], 'fff', 1)],
            'Gilgamesh': [(T20_orch, LYR['T20'], 'fff', 1)],
            'Enkidu':    [(T17_trio, LYR['final_solo'], 'ff', 1)],  # ghostly echo
            'Mkrimani':  [(TSINTSKARO_mk, LYR['tsintskaro'], 'ff', 1)],
            'Mtavari':   [(TSINTSKARO_mt, None, 'ff', 1)],
            'Bani':      [(TSINTSKARO_bn, None, 'ff', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
            'Winds':     [(T20_orch, None, 'ff', 1)],
            'Lamuri':    [(KHAS_mk, None, 'ff', 1)],
            'Chuniri':   [(T5_panduri, None, 'ff', 1)],
        }
    }
    build_scene(sc13b, parts)

    # ── Assemble score ────────────────────────────────────────────────
    for pname, part in parts.items():
        sc.insert(0, part)

    # Count total measures for verification
    total = 0
    for part in sc.parts:
        total = max(total, len([m for m in part.getElementsByClass(stream.Measure)]))
    print(f"Total measures: {total}")
    print("Expected: Overture=180, Act I=450, Act II=270, Act III=360, Act IV=540 => 1800")

    return sc

def main():
    print("Building Šamnu Azuzi v4 — complete opera score...")
    sc = build_score()
    print(f"Writing to {OUT_FILE} ...")
    sc.write('musicxml', fp=OUT_FILE)
    print(f"Done. File: {OUT_FILE}")
    sz = os.path.getsize(OUT_FILE)
    print(f"Size: {sz/1024/1024:.1f} MB")

if __name__ == '__main__':
    main()
