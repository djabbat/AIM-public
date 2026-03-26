#!/usr/bin/env python3
"""
ŠAMNU AZUZI v2 — COMPLETE OPERA FOR MUSESCORE 3
სამნუ ა-ზუ-ზი / Samnu A-zu-zi
Music and Libretto: Jaba Tkemaladze
~210 minutes · 5 Acts · 17 Scenes

PRINCIPLES:
  · All 20 themes T1–T20 from HARMONY.md/DeepSeek.md — EXACT note sequences
  · English + Georgian + transliteration lyrics on every vocal line
  · Every singer has independent instrumental countermelodies (not just doublings)
  · Music builds hypnotically — long arcs, not wave-like repetition
  · Tearjerker techniques: sudden major→minor, long pedal releases, silence, unisons
  · Svan principle: drone bass + two ornamental upper voices = soul
  · Structural arc: dissonance (T2 fff) → silence → resolution (T3 ff finale)
"""

import os
from music21 import (
    stream, note, chord, tempo, meter, key, dynamics,
    expressions, metadata, instrument, clef, bar, repeat, pitch
)
from music21.tempo import MetronomeMark

OUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "SAMNU_AZUZI_v2.musicxml")

# ══════════════════════════════════════════════════════════════════════
# EXACT THEMES FROM DeepSeek.md — T1 through T20
# Format: list of (pitch_or_R, quarter_duration)
# These are the canonical note sequences — do NOT alter them.
# ══════════════════════════════════════════════════════════════════════

# T1 — Tsintskaro (Harmony) — Gurian — D major
T1_mkrimani = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',1),('C#5',0.5),('D5',1.5)]
T1_mtavari  = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),
               ('C#5',0.5),('D4',1),('B3',0.5),('A4',1.5)]
T1_bani     = [('D3',1),('A3',0.5),('D4',0.5),('A3',1),('D3',0.5),
               ('A2',0.5),('D3',1),('A2',0.5),('D3',1.5)]

# T2 — Tsintskaro (Dissonance) — Atonal
T2_mkrimani = [('C#5',0.5),('G5',0.5),('A5',0.5),('F5',0.5),('B5',1),
               ('D#5',0.5),('G#5',0.5),('E5',1),('F5',1.5)]
T2_mtavari  = [('A4',0.5),('G#4',0.5),('G4',0.5),('F#4',0.5),('F4',1),
               ('E4',0.5),('D#4',0.5),('D4',1),('C#4',1.5)]
T2_bani     = [('D3',1),('D3',0.5),('Eb3',0.5),('D3',1),
               ('Eb3',0.5),('D3',0.5),('C#3',1),('D3',1.5)]

# T3 — Alilo (Finale) — D major — Gurian
T3_mkrimani = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',0.5),('C#5',0.5),('D5',0.5),('A4',0.5),('D5',1)]
T3_mtavari  = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),
               ('C#5',0.5),('D4',0.5),('B3',0.5),('A4',0.5),('F#4',0.5),('A4',1)]
T3_bani     = [('D3',1),('A3',0.5),('D4',0.5),('A3',1),('D3',0.5),
               ('A2',0.5),('D3',0.5),('A2',0.5),('D3',0.5),('D2',0.5),('D3',1)]

# T4 — Zari pure (Svan, A natural minor) — Lamuri
T4_lamuri   = [('D4',1.5),('R',0.5),('E4',1),('R',0.5),('G4',0.5),
               ('A4',1),('G4',0.5),('E4',1),('D4',1.5),('R',0.5),
               ('G4',1),('A4',0.5),('C5',0.5),('D5',1),('C5',0.5),
               ('A4',0.5),('G4',1.5),('R',0.5)]

# T5 — Zari transformation (Svan→Racha)
T5_lamuri   = [('D4',1),('E4',0.5),('G4',0.5),('A4',1),('B4',0.5),
               ('A4',0.5),('G4',1),('F#4',0.5),('E4',0.5),('D4',1)]
T5_panduri  = [('A4',1),('B4',0.5),('C5',0.5),('D5',1),('E5',0.5),
               ('D5',0.5),('C5',1),('B4',0.5),('A4',0.5),('G4',0.5),('A4',0.5)]

# T6 — Virishkhau (death, Svan) — fading
T6_lamuri   = [('D4',2),('E4',1.5),('G4',1.5),('A4',1),('G4',1),('E4',1),('D4',2)]
T6_enkidu   = [('A4',1.5),('G4',1),('E4',1),('D4',1.5),('C4',1),('A3',2),('R',1)]

# T7 — Nana / Iavnana (Megrelian lullaby)
T7_ninsun   = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),
               ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',1)]
T7_chuniri  = [('A3',2),('F3',1),('G3',1),('A3',1),('C4',1),('D4',2),('A3',2)]

# T8 — Mze Mikhvda (prophecy, Megrelian)
T8_ninsun   = [('A4',1),('C5',1),('B4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),
               ('D4',1),('F4',0.5),('A4',0.5),('C5',1),('B4',0.5),('A4',0.5),
               ('G4',1),('F4',0.5),('E4',0.5),('D4',2)]
T8_chuniri  = [('D3',2),('F3',1),('A3',1),('C4',2),('A3',1),('G3',1),('F3',2),('D3',2)]

# T9 — Odoia (Megrelian ritual)
T9_ninsun   = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),('R',0.5),
               ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',0.5),('R',0.5),
               ('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('F4',0.5),('E4',0.5),('D4',1)]

# T10 — Samkurao (Megrelian lament)
T10_ninsun  = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),('R',0.5),
               ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',0.5),('R',0.5),
               ('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('F4',0.5),
               ('E4',0.5),('D4',0.5),('C4',0.5),('D4',1.5)]

# T11 — Lile / Orovela finale (women's choir, 3 voices)
T11_sop1    = [('D5',1),('F5',0.5),('E5',0.5),('D5',1),('C5',0.5),('D5',0.5),
               ('F5',1),('G5',0.5),('A5',0.5),('G5',1),('F5',0.5),('E5',0.5),('D5',1)]
T11_sop2    = [('A4',1),('C5',0.5),('B4',0.5),('A4',1),('G4',0.5),('A4',0.5),
               ('C5',1),('D5',0.5),('E5',0.5),('D5',1),('C5',0.5),('B4',0.5),('A4',1)]
T11_alto    = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),
               ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',1)]

# T12 — Mtiuluri (Shamhat, Rachian, 5/8)
T12_shamhat = [('A4',0.75),('B4',0.5),('C5',0.75),('B4',0.5),('A4',0.5),
               ('G4',0.75),('A4',0.5),('B4',0.5),('C5',0.75),('A4',0.5),
               ('C5',0.75),('D5',0.5),('E5',0.75),('D5',0.5),('C5',0.5),
               ('B4',0.75),('C5',0.5),('D5',0.5),('E5',0.75),('C5',0.5)]
T12_panduri = [('A3',0.75),('E4',0.5),('A3',0.75),('E4',0.5),('C4',0.5),
               ('G3',0.75),('E4',0.5),('G3',0.5),('E4',0.75),('A3',0.5),
               ('A3',0.75),('E4',0.5),('A4',0.75),('E4',0.5),('C4',0.5),
               ('G3',0.75),('E4',0.5),('G3',0.5),('A3',0.75),('A3',0.5)]

# T13 — Gandagana (Shamhat+Enkidu duet, Rachian)
T13_shamhat = [('A4',0.75),('C5',0.5),('B4',0.75),('A4',0.5),('G4',0.5),
               ('A4',0.75),('B4',0.5),('C5',0.75),('A4',1)]
T13_enkidu  = [('A4',1),('G4',0.75),('E4',0.5),('D4',0.75),('C4',0.5),
               ('R',0.5),('D4',0.75),('E4',0.5),('G4',0.5),('A4',1)]

# T14 — Shamhat's Curse (a cappella, free)
T14_shamhat = [('A4',1),('G4',0.5),('F4',0.5),('E4',1),('D4',0.5),('C4',0.5),
               ('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',1),
               ('G4',1),('A4',0.5),('B4',0.5),('C5',1),('B4',0.5),('A4',0.5),
               ('G4',1),('F4',0.5),('E4',0.5),('D4',2),
               ('A5',2),('G5',1),('F5',0.5),('E5',0.5),('D5',0.5),('C5',0.5),('B4',0.5),('A4',2)]

# T15 — Khasanbegura (battle, Gurian, 5/8)
T15_orch    = [('D4',0.75),('F#4',0.5),('A4',0.75),('D5',0.5),('C5',0.5),
               ('B4',0.75),('A4',0.5),('G4',0.5),('F#4',0.75),('E4',0.5),('D4',1)]

# T16 — Beri-Berikoba (citizens chorus, Gurian)
T16_chorus  = [('G4',0.75),('B4',0.5),('D5',0.75),('C5',0.5),('B4',0.5),
               ('A4',0.75),('G4',0.5),('F#4',0.5),('G4',1)]

# T17 — Mravalzhamier (celebration, Gurian)
T17_trio    = [('G4',1),('B4',0.5),('D5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',1),('C5',0.5),('B4',0.5),('A4',0.5),('G4',1.5)]

# T18 — Rekhviashi (men's chorus, Svan)
T18_chorus  = [('D4',1),('E4',0.5),('G4',0.5),('A4',1),('C5',0.5),
               ('A4',0.5),('G4',1),('E4',0.5),('D4',1.5)]

# T19 — Humbaba's Theme (chromatic descent, Svan distorted)
T19_humbaba = [('D4',0.5),('Db4',0.5),('C4',0.5),('B3',0.5),('Bb3',1),
               ('A3',0.5),('Ab3',0.5),('G3',0.5),('F#3',0.5),('F3',1),
               ('E3',0.5),('Eb3',0.5),('D3',2)]

# T20 — Chakrulo orchestral (Bull of Heaven, 7/8)
T20_orch    = [('Bb4',1),('C5',0.75),('D5',0.75),('Eb5',1),('F5',0.75),
               ('G5',0.75),('F5',1),('Eb5',0.75),('D5',0.75),('C5',1),('Bb4',1.75)]

# ══════════════════════════════════════════════════════════════════════
# LYRICS: English + transliteration syllable lists
# ══════════════════════════════════════════════════════════════════════

LYR = {
    'T1_trio': ['ma-','ny','years...','ma-','ny','years...','bro-','ther-','hood'],
    'T1_geo':  ['მრა-','ვალ-','ჟამ-','ი-','ე-','რი...','ძმ-','ო-','ბა'],

    'T2_mk':   ['i-','i-','i-','dis-','so-','nance','falls','a-','part...'],
    'T2_mt':   ['i-','i-','i-','dark-','ness','grows','in-','side','me...'],
    'T2_bn':   ['D—','—','—Eb—','—','—','D—','—','—D'],

    'T3_fin':  ['A-','li-','lo!','ma-','ny','years!','bro-','ther-','hood','lives','on!'],
    'T3_geo':  ['ა-','ლი-','ლო!','მრა-','ვალ-','ჟა-','მი-','ე-','რი!','ძმ-','ო-','ბა!'],

    'T7_en':   ['Na-','na,','na-','na,','my','child,','sleep','in','peace,','sleep','now','child','sleep'],
    'T7_geo':  ['ნა-','ნა,','ნა-','ნა,','შვი-','ლი,','ძი-','ნე','ამ','ღა-','მეს','ნა-','ნა'],

    'T8_en':   ['Hear','me,','child—','what','I','now','tell','you:','the','star','that','fell','will','come','as','broth-','er'],
    'T8_geo':  ['მო-','მის-','მი-','ნე,','შვი-','ლო,','რას','გეტ-','ყვი:','ვარ-','სკ-','ვლ-','ა-','ვი','მო-','ვა','ძმ-','ა-','დ'],

    'T9_en':   ['O-','do-','ia,','o-','do-','ia,', 'may','the','road','be','clear','for','you,','my','child-','ren!',
                'O-','do-','ia,','may','the','sun','look','down','on','you!'],
    'T9_geo':  ['ო-','დო-','ია,','ო-','დო-','ია,', 'გზა','გა-','გი-','მარ-','თ-','ლ-','ოს,','შვი-','ლე-','ბო!',
                'ო-','დო-','ია,','მზე','თ-','ქ-','ვ-','ე-','ნ','გ-','ა-','დ-','მ-','ო-','გ-','ი-','ხ-','ე-','დ-','ოს!'],

    'T10_en':  ['Sam-','ku-','ra-','o,','sam-','ku-','ra-','o,','my','child,','my','child,',
                'come','back','to','me,','o-','do-','ia...','sam-','ku-','ra-','o'],
    'T10_geo': ['სამ-','კუ-','რა-','ო,','სამ-','კუ-','რა-','ო,','ჩ-','ქი-','მი','ჭ-',
                'ყ-','ვი-','დე,','სამ-','კუ-','რა-','ო...','ო-','დო-','ი-','ა'],

    'T11_en':  ['Li-','le,','li-','le,','o-','ro-','ve-','la!','Life','goes','on,','life','goes','on!'],

    'T12_en':  ['From','the','moun-','tain','I','came','down!','I','am','fire!','I','am','air!',
                'I','am','wind','and','vine!','Mine!','All','mine!'],
    'T12_geo': ['მთი-','დ-','ა-','ნ','ჩა-','მო-','ვ-','ე-','დი!','ვ-','არ','ც-','ე-','ც-','ხ-','ლი!'],

    'T13_sh':  ['Gan-','da-','ga-','na,','come','to','me,','no','fear!'],
    'T13_ek':  ['I...','re-','mem-','ber...','some-','thing...','who...','am','I?'],
    'T13_geo_sh': ['გ-','ა-','ნ-','და-','გა-','ნა,','მო-','დი','ჩ-','ემ-','თ-','ა-','ნ!'],
    'T13_geo_ek': ['ვ-','არ','ა-','დ-','ა-','მი-','ა-','ნი?','ვ-','ინ','ვ-','ა-','რ?'],

    'T14_en':  ['Curs-','ed','be','this','day!','Curs-','ed!','I','killed','him','with','my',
                'love!','I','killed','him!','I!','I!',
                'A—','(scream)','G—','F—','E—','D—','C—','B—','A—'],
    'T14_geo': ['და-','წყ-','ევ-','ლი-','ლი','ი-','ყ-','ო-','ს','ე-','ს','დ-',
                'ღ-','ე!','მ-','ო-','ვ-','კ-','ა-','ლი!','მ-','ე!','მ-','ე!',
                'ა—','—','—','—','—','—','—','—','—'],

    'T15_en':  ['For-','ward!','Uruk!','Strike!','For','the','king!','For','bro-','ther-','hood!'],
    'T16_en':  ['U-','ruk','mourns!','The','king','will','not','hear','us!'],
    'T16_geo': ['ურ-','უ-','ქი','გლ-','ო-','ვ-','ო-','ბ-','ს!'],

    'T17_en':  ['Ma-','ny','years!','Ma-','ny','years!','Glo-','ry','to','bro-','ther-','hood!'],
    'T17_geo': ['მრა-','ვ-','ა-','ლ-','ჟ-','ა-','მ-','ი-','ე-','რ-','ი!'],

    'T18_en':  ['Rekh-','vi-','ash,','rekh-','vi-','ash!','Beau-','ty!','Strength!'],
    'T18_geo': ['რ-','ე-','ხ-','ვი-','ა-','შ!','მ-','ა-','ყ-','ვ-','ა-','ლ!'],

    'T19_en':  ['I','am','the','for-','est.','I','am','the','earth.','You','will','not','pass.'],
    'T19_geo': ['ვ-','ა-','რ','ტ-','ყ-','ე.','ვ-','ა-','რ','მ-','ი-','წ-','ა.'],

    'T20_en':  ['Vic-','to-','ry!','The','bull','falls!','We','stand!','We','stand!','Uruk!'],
    'T20_geo': ['გ-','ა-','მ-','ა-','რ-','ჯ-','ვ-','ე-','ბ-','ა!','ვ-','ა-','ო!'],

    'gil_alone': ['I','was.','I','am.','I','will','be.'],
    'enkidu_first': ['I...','am...','I?','Clay...','and...','blood?','I...','am...'],
    'brothers': ['You','are','my','bro-','ther.','Un-','til','death.'],
    'lament': ['Who','are','you?!','My','three!','Where','is','my','bro-','ther?!','Where?!'],
    'shadows': ['Who','was','there?','Who','comes?','Who','seeks','death?'],
}

# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def N(p, dur=1.0, lyr=None, dyn_str=None, oct_shift=0, fermata=False):
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

def theme(t, lyr=None, dyn=None, osh=0, fermata_last=False):
    """Convert [(pitch,dur),...] → [Note/Rest,...]"""
    out = []
    for i, (p, d) in enumerate(t):
        l = lyr[i] if lyr and i < len(lyr) else None
        d0 = dyn if i == 0 else None
        fm = fermata_last and i == len(t)-1
        out.append(N(p, d, l, d0, osh, fm))
    return out

def beats_per_measure(ts_str):
    n, d = ts_str.split('/')
    return 4.0 * int(n) / int(d)

def pack(notes_list, ts_str='4/4', ks=None, bpm=None, txt=None,
         cl_str=None, rep_start=False, rep_end=False, rep_times=2):
    """Pack flat note list into Measure objects with bar repeat marks."""
    bpm_val = beats_per_measure(ts_str)
    measures = []
    cur = stream.Measure()
    if cl_str == 'bass':
        cur.append(clef.BassClef())
    elif cl_str == 'treble8':
        cur.append(clef.Treble8vbClef())
    elif cl_str:
        cur.append(clef.TrebleClef())
    if ks is not None:
        cur.append(key.KeySignature(ks))
    cur.append(meter.TimeSignature(ts_str))
    if bpm:
        cur.append(MetronomeMark(number=bpm))
    if txt:
        cur.append(expressions.TextExpression(txt))
    if rep_start:
        cur.leftBarline = bar.Repeat(direction='start')
    cb = 0.0
    for n in notes_list:
        nd = n.quarterLength
        if cb + nd > bpm_val + 0.001:
            rem = bpm_val - cb
            if rem > 0.01:
                cur.append(note.Rest(quarterLength=rem))
            measures.append(cur)
            cur = stream.Measure()
            cur.append(meter.TimeSignature(ts_str))
            cb = 0.0
        cur.append(n)
        cb += nd
    rem = bpm_val - cb
    if rem > 0.01:
        cur.append(note.Rest(quarterLength=rem))
    if rep_end:
        cur.rightBarline = bar.Repeat(direction='end', times=rep_times)
    measures.append(cur)
    return measures

def add(part, measures_list):
    for m in measures_list:
        part.append(m)

def rests(n_measures, ts_str='4/4'):
    bpm = beats_per_measure(ts_str)
    result = []
    for _ in range(n_measures):
        m = stream.Measure()
        m.append(meter.TimeSignature(ts_str))
        # Split into representable rest values
        remaining = bpm
        for rest_dur in [4.0, 3.0, 2.0, 1.5, 1.0, 0.5, 0.25]:
            while remaining >= rest_dur - 0.001:
                m.append(note.Rest(quarterLength=rest_dur))
                remaining -= rest_dur
                if remaining < 0.001:
                    break
            if remaining < 0.001:
                break
        result.append(m)
    return result

def silence_measure(ts_str='4/4', txt=None):
    m = stream.Measure()
    m.append(meter.TimeSignature(ts_str))
    bpm = beats_per_measure(ts_str)
    r = note.Rest(quarterLength=bpm)
    r.expressions.append(expressions.TextExpression('(silence)' if not txt else txt))
    m.append(r)
    return m

def crescendo_rests(n_measures, ts_str='4/4', from_dyn='ppp', to_dyn='ff'):
    """Silent measures with crescendo hairpin text."""
    ms = rests(n_measures, ts_str)
    if ms:
        ms[0].insert(0, expressions.TextExpression(f'◁ cresc. {from_dyn}→{to_dyn}'))
    return ms

# ══════════════════════════════════════════════════════════════════════
# ORCHESTRAL COUNTERMELODIES (independent lines, not doublings)
# ══════════════════════════════════════════════════════════════════════

# Strings ostinato under T1 (D major pedal with inner movement)
STR_T1_OSTINATO = [('D3',1),('F#3',0.5),('A3',0.5),('D3',1),('A3',0.5),('F#3',0.5),
                   ('D3',1),('A3',0.5),('D4',0.5),('A3',1),('F#3',0.5),('D3',1.5)]

# Cello countermelody under T7 (Nana) — rising warmth
CELLO_T7 = [('D2',2),('F2',1),('A2',1),('C3',1),('A2',1),('G2',1),('F2',2),('D2',2)]

# Winds counterpoint under T8 (prophecy) — rising to climax
WINDS_T8 = [('A3',1),('C4',1),('D4',1),('F4',1),('E4',2),('D4',1),('C4',1),('A3',2),
            ('F3',1),('A3',1),('C4',2),('D4',2),('A3',4)]

# Strings pizz under T12 (Mtiuluri) — driving 5/8 pulse
STR_T12_PIZZ = [('A2',0.75),('E3',0.5),('A2',0.75),('E3',0.5),('C3',0.5),
                ('G2',0.75),('D3',0.5),('A2',0.75),('E3',0.5),('A2',0.5),
                ('A2',0.75),('E3',0.5),('A2',0.75),('C3',0.5),('E3',0.5),
                ('G2',0.75),('D3',0.5),('G2',0.5),('E3',0.75),('A2',0.5)]

# Brass punctuation under T20 (Chakrulo) — off-beat accents
BRASS_T20 = [('R',1),('Bb2',0.75),('F3',0.75),('R',1),('D3',0.75),
             ('F3',0.75),('Bb3',1),('R',0.75),('Bb2',0.75),('F3',0.75),('D3',1.5)]

# Piano under T2 (dissonance) — chromatic cluster
PIANO_T2 = [('C#3',0.5),('G3',0.5),('C#3',0.5),('Eb3',0.5),('F3',1),
            ('D3',0.5),('Ab3',0.5),('D3',1),('C#3',1.5)]

# Cello solo (Act V descent D3→0)
CELLO_FINAL = [('D3',2),('C#3',2),('C3',2),('B2',2),('Bb2',2),('A2',2),
               ('G2',2),('F#2',2),('D2',4)]

# ══════════════════════════════════════════════════════════════════════
# PARTS FACTORY
# ══════════════════════════════════════════════════════════════════════

def make_parts():
    def P(inst_obj, name, abbr):
        p = stream.Part()
        p.partName = name
        p.partAbbreviation = abbr
        p.insert(0, inst_obj)
        return p
    return {
        # Soloists
        'G':  P(instrument.Baritone(),    'Gilgamesh (Bar.)',        'Gl'),
        'E':  P(instrument.Tenor(),       'Enkidu (Ten.)',           'En'),
        'NS': P(instrument.MezzoSoprano(),'Ninsun (Mez.)',           'Ns'),
        'SH': P(instrument.Soprano(),     'Shamhat (Sop.)',          'Sh'),
        'HU': P(instrument.Bass(),        'Humbaba/Utnapishtim (Bs)','Hu'),
        # Trio (Gilgamesh's three inner voices)
        'MK': P(instrument.Tenor(),       'Mkrimani (CTen.)',        'Mk'),
        'MT': P(instrument.Tenor(),       'Mtavari (Ten.)',          'Mt'),
        'BN': P(instrument.Bass(),        'Bani (Bass)',             'Bn'),
        # Chorus
        'CH': P(instrument.Vocalist(),    'Chorus (SATB)',           'Ch'),
        # Georgian instruments
        'LM': P(instrument.Flute(),       'Lamuri (Svan flute)',     'Lm'),
        'CN': P(instrument.Violin(),      'Chuniri (Svan fiddle)',   'Cn'),
        'PD': P(instrument.Violin(),      'Panduri (Kakh. lute)',    'Pd'),
        # Orchestra
        'ST': P(instrument.StringInstrument(),'Strings',            'St'),
        'WD': P(instrument.Oboe(),        'Winds',                  'Wd'),
        'BR': P(instrument.Horn(),        'Brass',                  'Br'),
        'CL': P(instrument.Violoncello(), 'Cello solo',             'Cl'),
        'PI': P(instrument.Piano(),       'Piano',                  'Pi'),
    }

ALL_PARTS = ['G','E','NS','SH','HU','MK','MT','BN','CH','LM','CN','PD','ST','WD','BR','CL','PI']

def fill(p, ts_str, n_measures):
    """fill(part, time_sig_str, n_measures)"""
    for m in rests(n_measures, ts_str):
        p.append(m)

# ══════════════════════════════════════════════════════════════════════
# ACT I — TYRANNY AND SOLITUDE (~35 min)
# ══════════════════════════════════════════════════════════════════════

def act_I(P):
    G=P['G']; E=P['E']; NS=P['NS']; SH=P['SH']; HU=P['HU']
    MK=P['MK']; MT=P['MT']; BN=P['BN']; CH=P['CH']
    LM=P['LM']; CN=P['CN']; PD=P['PD']
    ST=P['ST']; WD=P['WD']; BR=P['BR']; CL=P['CL']; PI=P['PI']

    # ── SCENE 1 — Uruk in Mourning (G minor, 5/8, ♩.=58) ──────────────
    # T16: Beri-Berikoba — Chorus ff, 5 repetitions (not waves: each entry
    # has a new dynamic instruction and text layer building the crowd fury)
    lyr16 = LYR['T16_en']
    lyr16g = LYR['T16_geo']
    # Verse 1: mf (distant crowd), Verse 2: f, Verse 3: ff (fury peaks)
    for n_rep, dyn_v, txt_v in [
        (1,'mf','Sc.1 | Uruk in Mourning | G minor | 5/8 | ♩.=58'),
        (2,'f', None),
        (3,'ff',None),
    ]:
        nts = theme(T16_chorus, lyr16 if n_rep == 1 else lyr16g, dyn_v)
        ms = pack(nts, '5/8', ks=-2, bpm=58 if n_rep==1 else None, txt=txt_v)
        add(CH, ms)
    # Silence — the crowd holds its breath
    CH.append(silence_measure('5/8', '(the crowd freezes)'))

    # T1 Trio: ppp — first emergence from shadow
    # MK highest voice — barely audible
    add(MK, pack(theme(T1_mkrimani, LYR['T1_trio'], 'ppp'),
                 '4/4', ks=2, bpm=72, txt='T1 — Tsintskaro: inner voices emerge (ppp)'))
    add(MT, pack(theme(T1_mtavari, None, 'ppp'), '4/4', ks=2))
    add(BN, pack(theme(T1_bani,    None, 'ppp'), '4/4', ks=2, cl_str='bass'))

    # Gilgamesh arioso — "I am King!" — brass enters on key word
    gil_lyr = ['I','am','king!','I','am','god!','These','walls—','my','name.',
               'This','ci-','ty—','my','glo-','ry!','But...','why','am','I','a-','lone?']
    gil_notes = [('G3',1),('Bb3',0.5),('D4',0.5),('Bb3',1),('G3',0.5),
                 ('F3',0.5),('G3',1),('D4',1),('Bb3',0.5),('G3',0.5),
                 ('D4',1),('F4',0.5),('G4',0.5),('Bb3',1),('D4',0.5),('G3',0.5),
                 ('R',0.5),('F3',0.5),('Eb3',1),('D3',0.5),('C3',0.5),('D3',2)]
    add(G, pack(theme(gil_notes, gil_lyr, 'mf'),
                '4/4', ks=-2, bpm=63, txt='No.3 — Gilgamesh Arioso | "I am King!"'))
    # Brass: enters ff on "I am King", then silent
    br_notes = [('G2',0.5),('R',0.5),('Bb2',0.5),('R',0.5),('D3',1),('G2',1),
                ('R',4),('R',4),('R',4),('R',4)]
    add(BR, pack(theme(br_notes, None, 'ff'), '4/4', ks=-2))
    # Cello solo after "alone" — pure, tender
    cl_notes = [('R',4),('R',4),('R',4),('D3',1),('F3',1),('A3',1),('G3',1),
                ('F3',1),('E3',1),('D3',2)]
    add(CL, pack(theme(cl_notes, None, 'p'), '4/4', ks=-2, cl_str='bass'))

    fill(E,  '4/4', 8); fill(NS, '4/4', 8); fill(SH, '4/4', 8)
    fill(HU, '4/4', 8); fill(LM, '4/4', 8); fill(CN, '4/4', 8)
    fill(PD, '4/4', 8); fill(ST, '4/4', 8); fill(WD, '4/4', 8); fill(PI, '4/4', 8)
    # Align 5/8 chorus rests
    fill(G,  '5/8', 4); fill(MK,'5/8',4); fill(MT,'5/8',4); fill(BN,'5/8',4)

    # ── SCENE 2 — Three Dreams (D minor, ♩=60) ────────────────────────
    # T7 Nana: Ninsun + Chuniri — warm lullaby under the night sky
    ninsun_lyr = LYR['T7_en']
    add(NS, pack(theme(T7_ninsun, ninsun_lyr, 'p'),
                 '4/4', ks=-1, bpm=60, txt='Sc.2 — Three Dreams | T7 Nana (Megrelian lullaby)'))
    add(CN, pack(theme(T7_chuniri, None, 'pp'), '4/4', ks=-1, cl_str='bass'))
    # Strings con sordino — slow rising countermelody (warmth)
    add(ST, pack(theme(STR_T1_OSTINATO, None, 'pp'), '4/4', ks=-1))

    # T1 Trio — Tsintskaro FULL ff (first peak — this is the "tearjerker" moment):
    # Three voices converge into perfect harmony after the dream
    add(MK, pack(theme(T1_mkrimani, LYR['T1_trio'], 'ff'),
                 '4/4', ks=2, bpm=72, txt='T1 ff — first full Trio harmony (D major)'))
    add(MT, pack(theme(T1_mtavari, None, 'ff'), '4/4', ks=2))
    add(BN, pack(theme(T1_bani,    None, 'ff'), '4/4', ks=2, cl_str='bass'))

    # T8 Mze Mikhvda — Ninsun's prophecy (largo, builds to climax)
    add(NS, pack(theme(T8_ninsun, LYR['T8_en'], 'mp'),
                 '4/4', ks=-1, bpm=50, txt='T8 Mze Mikhvda — Ninsun\'s Prophecy (Largo maestoso)'))
    add(CN, pack(theme(T8_chuniri, None, 'p'), '4/4', ks=-1, cl_str='bass'))
    # Winds rise with countermelody — prophecy builds
    add(WD, pack(theme(WINDS_T8, None, 'mp'), '4/4', ks=-1))
    # Cello warmth
    add(CL, pack(theme(CELLO_T7, None, 'p'), '4/4', ks=-1, cl_str='bass'))

    fill(G,'4/4',8); fill(E,'4/4',8); fill(SH,'4/4',8); fill(HU,'4/4',8)
    fill(LM,'4/4',8); fill(PD,'4/4',8); fill(BR,'4/4',8); fill(PI,'4/4',8)
    fill(CH,'4/4',8)

    # ── SCENE 3 — Creation of Enkidu (A natural minor, senza misura) ──
    # T4 Zari (Lamuri — Svan bone flute) — pure, archaic
    add(LM, pack(theme(T4_lamuri, None, 'p'),
                 '4/4', bpm=40, txt='Sc.3 — Enkidu\'s Creation | T4 Zari (Svan flute, senza misura)'))
    # Enkidu's vocalize mirrors lamuri — man and nature one language
    add(E, pack(theme([('D4',2),('R',1),('E4',1.5),('R',0.5),('G4',2),('A4',2),('G4',1),('E4',1),('D4',2)],
                      LYR['enkidu_first'], 'pp'), '4/4'))
    # Chorus offstage: Lile (low voices, clay/earth)
    ch_lile = [('D3',1),('D3',1),('F3',0.5),('E3',0.5),('D3',1),('C3',1),
               ('D3',2),('F3',1),('G3',1),('A3',2),('G3',1),('F3',1),('D3',2)]
    add(CH, pack(theme(ch_lile, ['Li-','le,','li-','le,','clay...','earth...',
                                  'Li-','le,','li-','le,','En-','ki-','du...'],
                       'pp'), '4/4', bpm=40, txt='Men\'s chorus offstage — Lile (Svan creation prayer)'))
    # Chuniri: Svan drone
    add(CN, pack(theme([('D3',4),('A3',4),('D3',4),('A3',4)], None, 'pp'), '4/4'))

    fill(G,'4/4',4); fill(NS,'4/4',4); fill(SH,'4/4',4); fill(HU,'4/4',4)
    fill(MK,'4/4',4); fill(MT,'4/4',4); fill(BN,'4/4',4)
    fill(PD,'4/4',4); fill(ST,'4/4',4); fill(WD,'4/4',4)
    fill(BR,'4/4',4); fill(CL,'4/4',4); fill(PI,'4/4',4)


# ══════════════════════════════════════════════════════════════════════
# ACT II — TWO ORIGINS MEET (~40 min)
# ══════════════════════════════════════════════════════════════════════

def act_II(P):
    G=P['G']; E=P['E']; NS=P['NS']; SH=P['SH']; HU=P['HU']
    MK=P['MK']; MT=P['MT']; BN=P['BN']; CH=P['CH']
    LM=P['LM']; CN=P['CN']; PD=P['PD']
    ST=P['ST']; WD=P['WD']; BR=P['BR']; CL=P['CL']; PI=P['PI']

    # ── SCENE 4 — Shamhat at the Spring (A major, 5/8, ♩.=60) ─────────
    # T12 Mtiuluri: Shamhat enters — fire, mountain energy
    add(SH, pack(theme(T12_shamhat, LYR['T12_en'], 'f'),
                 '5/8', ks=3, bpm=60, txt='Sc.4 — Shamhat | T12 Mtiuluri (Rachian, 5/8) | ff'))
    # Panduri: driving 5/8 ostinato
    add(PD, pack(theme(T12_panduri, None, 'mf'), '5/8', ks=3))
    # Strings pizzicato: rhythmic punctuation
    add(ST, pack(theme(STR_T12_PIZZ, None, 'mp'), '5/8', ks=3))
    # Lamuri: T5 Zari transformation — Enkidu's nature hears her, begins to change
    add(LM, pack(theme(T5_lamuri, None, 'mf'),
                 '4/4', ks=0, bpm=80, txt='T5 — Zari transformation (lamuri hears the world change)'))
    # Enkidu: silent, watching
    fill(E,'5/8',8); fill(G,'5/8',8); fill(NS,'5/8',8); fill(HU,'5/8',8)
    fill(MK,'5/8',8); fill(MT,'5/8',8); fill(BN,'5/8',8)
    fill(CN,'5/8',8); fill(WD,'5/8',8); fill(BR,'5/8',8); fill(CL,'5/8',8); fill(PI,'5/8',8)
    fill(CH,'5/8',8)

    # ── SCENE 5 — Seven Days (A minor→A major, 7 variations) ──────────
    # T13 Gandagana: Shamhat seduces — duet 5/8 vs 4/4
    add(SH, pack(theme(T13_shamhat, LYR['T13_sh'], 'mp'),
                 '5/8', ks=3, bpm=54, txt='Sc.5 — Seven Days | T13 Gandagana (duet)'))
    add(E,  pack(theme(T13_enkidu,  LYR['T13_ek'], 'p'),
                 '4/4', ks=0, bpm=54, txt='Enkidu: who am I? (A minor, 4/4 vs Shamhat 5/8)'))
    # Panduri: Rachian dance ostinato
    add(PD, pack(theme([(p,d) for p,d in T12_panduri[:10]], None, 'mp'), '5/8', ks=3))
    # Lamuri: T5 continues — last transformation phrase
    add(LM, pack(theme(T5_panduri, None, 'p'), '4/4', ks=0))

    # T5 Var VII — Enkidu becomes human: A major, 5/8, ecstatic
    enkidu_human = [('A4',0.75),('B4',0.5),('C#5',0.75),('E5',0.5),('D5',0.5),
                    ('C#5',0.75),('B4',0.5),('A4',0.75),('B4',0.5),('A4',0.5),
                    ('A4',1.25),('R',0.5)]
    add(E, pack(theme(enkidu_human,
                      ['Sham-','khat!','I','am—','I','am—',
                       '(pause)','A','hu-','man','be-','ing!'],
                      'ff'), '5/8', ks=3, txt='Enkidu: "I am a human being!" (A major, 5/8, ff)'))

    fill(G,'5/8',8); fill(NS,'5/8',8); fill(HU,'5/8',8)
    fill(MK,'5/8',8); fill(MT,'5/8',8); fill(BN,'5/8',8)
    fill(ST,'5/8',8); fill(WD,'5/8',8); fill(BR,'5/8',8); fill(CL,'5/8',8); fill(PI,'5/8',8)
    fill(CH,'5/8',8); fill(CN,'5/8',8)

    # ── SCENE 6 — The Duel (D minor→D major, 5/8, ♩.=66) ─────────────
    # T15 Khasanbegura: battle energy, orchestra + voices
    add(G, pack(theme(T15_orch,
                      ['I','am','king!','Two-','thirds','god!','I','am','Uruk!','I','am','walls!'],
                      'ff'), '5/8', ks=-1, bpm=66, txt='Sc.6 — Duel | T15 Khasanbegura (Gurian, 5/8, ff)'))
    add(E, pack(theme(T15_orch,
                      ['I','am','earth!','I','am','for-','est!','I','am','wind!','I','am','free!'],
                      'ff', osh=0), '5/8', ks=-1))
    # T1 — Trio ff at the moment of recognition (D major — D minor combat melts)
    add(MK, pack(theme(T1_mkrimani, LYR['T1_trio'], 'ff'),
                 '4/4', ks=2, bpm=72, txt='T1 ff — Trio: moment of recognition (D major)'))
    add(MT, pack(theme(T1_mtavari, None, 'ff'), '4/4', ks=2))
    add(BN, pack(theme(T1_bani, None, 'ff'), '4/4', ks=2, cl_str='bass'))
    # Brass accents
    add(BR, pack(theme([('D3',0.75),('R',0.5),('F3',0.5),('A3',0.5),('D3',0.5),
                        ('R',0.5),('D3',0.75),('A3',0.5),('F3',0.5),('D3',1)],
                       None, 'fff'), '5/8', ks=-1))
    # Strings: martial ostinato
    add(ST, pack(theme(STR_T12_PIZZ, None, 'f'), '5/8', ks=-1))

    fill(NS,'5/8',8); fill(SH,'5/8',8); fill(HU,'5/8',8)
    fill(LM,'5/8',8); fill(CN,'5/8',8); fill(PD,'5/8',8)
    fill(WD,'5/8',8); fill(CL,'5/8',8); fill(PI,'5/8',8); fill(CH,'5/8',8)

    # ── SCENE 7 — Brotherhood (G major, ♩=72) ────────────────────────
    # T17 Mravalzhamier ff — all voices in full festive harmony
    add(MK, pack(theme(T17_trio, LYR['T17_geo'], 'ff'),
                 '4/4', ks=1, bpm=72, txt='Sc.7 — Brotherhood | T17 Mravalzhamier (ff, G major)'))
    add(MT, pack(theme(T17_trio, LYR['T17_en'], 'ff', osh=0), '4/4', ks=1))
    add(BN, pack(theme(T17_trio, None, 'ff', osh=-1), '4/4', ks=1, cl_str='bass'))
    # T18 Rekhviashi: men's chorus — Svan brotherhood
    add(CH, pack(theme(T18_chorus, LYR['T18_en'], 'f'),
                 '4/4', ks=-1, bpm=66, txt='T18 Rekhviashi — Svan men\'s brotherhood song'))
    # Duet: brotherhood oath a cappella — strings fade out
    add(G, pack(theme([('G3',1.5),('Bb3',0.5),('D4',2),('G3',1),('F3',1),('Eb3',2),('D3',4)],
                      LYR['brothers'], 'p'),
                '4/4', ks=-1, bpm=54, txt='Brotherhood Oath (a cappella, D minor→D major)'))
    add(E, pack(theme([('D4',1.5),('F4',0.5),('A4',2),('D4',1),('C4',1),('Bb3',2),('A3',4)],
                      LYR['brothers'], 'p'), '4/4', ks=-1))
    # Bani — "until death" — D3, long
    add(BN, pack(theme([('R',4),('R',4),('D3',4),('D3',4)], None, 'pp'), '4/4', ks=-1))

    fill(NS,'4/4',8); fill(SH,'4/4',8); fill(HU,'4/4',8)
    fill(LM,'4/4',8); fill(CN,'4/4',8); fill(PD,'4/4',8)
    fill(ST,'4/4',8); fill(WD,'4/4',8); fill(BR,'4/4',8); fill(CL,'4/4',8); fill(PI,'4/4',8)


# ══════════════════════════════════════════════════════════════════════
# ACT III — THE CEDAR FOREST (~40 min)
# ══════════════════════════════════════════════════════════════════════

def act_III(P):
    G=P['G']; E=P['E']; NS=P['NS']; SH=P['SH']; HU=P['HU']
    MK=P['MK']; MT=P['MT']; BN=P['BN']; CH=P['CH']
    LM=P['LM']; CN=P['CN']; PD=P['PD']
    ST=P['ST']; WD=P['WD']; BR=P['BR']; CL=P['CL']; PI=P['PI']

    # ── SCENE 8 — Ninsun's Blessing (D aeolian, ♩=70) ─────────────────
    # T9 Odoia — Megrelian temple chant
    add(NS, pack(theme(T9_ninsun, LYR['T9_en'][:16], 'p'),
                 '4/4', ks=-1, bpm=70, txt='Sc.8 — Ninsun\'s Blessing | T9 Odoia (Megrelian ritual)'))
    # Chuniri solo — antiphonal with voice
    add(CN, pack(theme(T7_chuniri, None, 'pp'), '4/4', ks=-1))
    # T1 Trio ppp — in shadow behind the altar (they feel Ninsun's blessing)
    add(MK, pack(theme(T1_mkrimani, None, 'ppp'), '4/4', ks=2, bpm=70))
    add(MT, pack(theme(T1_mtavari, None, 'ppp'), '4/4', ks=2))
    add(BN, pack(theme(T1_bani, None, 'ppp'), '4/4', ks=2, cl_str='bass'))
    # Strings con sordino — reverential
    add(ST, pack(theme(STR_T1_OSTINATO, None, 'ppp'), '4/4', ks=-1))

    fill(G,'4/4',8); fill(E,'4/4',8); fill(SH,'4/4',8); fill(HU,'4/4',8)
    fill(LM,'4/4',8); fill(PD,'4/4',8); fill(WD,'4/4',8)
    fill(BR,'4/4',8); fill(CL,'4/4',8); fill(PI,'4/4',8); fill(CH,'4/4',8)

    # ── SCENE 9 — Forest Path + Humbaba (C# minor, ♩=40) ──────────────
    # T19 Humbaba — chromatic descent (terror, the earth speaks)
    add(HU, pack(theme(T19_humbaba, LYR['T19_en'], 'mf'),
                 '4/4', ks=4, bpm=40, txt='Sc.9 — Humbaba | T19 (chromatic descent, C# minor, Lento lugubre)'))
    # Canon of T19 in low strings — echo
    add(ST, pack(theme(T19_humbaba, None, 'p'), '4/4', ks=4))
    # T6 Virishkhau (lamuri) — still present but fading (mp)
    add(LM, pack(theme(T6_lamuri, None, 'mp'),
                 '4/4', ks=-1, bpm=40, txt='T6 Virishkhau — lamuri fading (mp)'))
    # Winds — distant, dissonant
    add(WD, pack(theme([('C#4',2),('B3',2),('A3',2),('G#3',2),('F#3',4)], None, 'p'), '4/4', ks=4))
    # Piano — low cluster
    add(PI, pack(theme(PIANO_T2, None, 'p'), '4/4', ks=4))

    fill(G,'4/4',8); fill(E,'4/4',8); fill(NS,'4/4',8); fill(SH,'4/4',8)
    fill(MK,'4/4',8); fill(MT,'4/4',8); fill(BN,'4/4',8)
    fill(CN,'4/4',8); fill(PD,'4/4',8); fill(BR,'4/4',8); fill(CL,'4/4',8); fill(CH,'4/4',8)

    # ── SCENE 10 — Enkidu's Death (D minor, ♩=40, T6 pppp→0) ──────────
    # T6 Virishkhau — dying, each note with fermata
    t6_dying = theme(T6_lamuri, None, 'pp', fermata_last=True)
    add(LM, pack(t6_dying, '4/4', ks=-1, bpm=40,
                 txt='Sc.10 — Enkidu\'s Death | T6 pppp→0 | (fermata on each note, dying)'))
    LM.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('pppp → 0 — Lamuri falls silent forever'))

    # T10 Samkurao — Ninsun's lament, the most heartbreaking
    add(NS, pack(theme(T10_ninsun, LYR['T10_en'][:23], 'p'),
                 '4/4', ks=-1, bpm=46, txt='T10 Samkurao — Ninsun\'s lament (Lento doloroso)'))
    add(CN, pack(theme(T7_chuniri, None, 'ppp'), '4/4', ks=-1))
    # Cello solo — ascending then falling (grief arc)
    add(CL, pack(theme([('D3',1),('F3',1),('A3',1),('D4',2),('C4',1),('Bb3',1),('A3',1),
                        ('G3',1),('F3',2),('D3',4)], None, 'p'), '4/4', ks=-1, cl_str='bass'))
    # T2 — first real crack: Trio dissonant entrance
    add(MK, pack(theme(T2_mkrimani, LYR['T2_mk'], 'mf'),
                 '4/4', ks=0, bpm=46, txt='T2 — Trio\'s first dissonance (soul fractures)'))
    add(MT, pack(theme(T2_mtavari, LYR['T2_mt'], 'mf'), '4/4', ks=0))
    add(BN, pack(theme(T2_bani, LYR['T2_bn'], 'mf'), '4/4', ks=0, cl_str='bass'))
    # Silence — measure of pure silence after Enkidu dies
    for part_name in ['G','E','SH','HU','ST','WD','BR','PI','CH','PD']:
        P[part_name].append(silence_measure('4/4', '(Enkidu is dead — silence)'))

    fill(G,'4/4',8); fill(E,'4/4',8); fill(SH,'4/4',8); fill(HU,'4/4',8)
    fill(ST,'4/4',8); fill(WD,'4/4',8); fill(BR,'4/4',8); fill(PI,'4/4',8)
    fill(CH,'4/4',8); fill(PD,'4/4',8)


# ══════════════════════════════════════════════════════════════════════
# ACT IV — BULL OF HEAVEN AND JUDGMENT (~45 min)
# ══════════════════════════════════════════════════════════════════════

def act_IV(P):
    G=P['G']; E=P['E']; NS=P['NS']; SH=P['SH']; HU=P['HU']
    MK=P['MK']; MT=P['MT']; BN=P['BN']; CH=P['CH']
    LM=P['LM']; CN=P['CN']; PD=P['PD']
    ST=P['ST']; WD=P['WD']; BR=P['BR']; CL=P['CL']; PI=P['PI']

    # ── SCENE 11 — Ishtar + Bull of Heaven (Bb major, 7/8, ♩=120) ─────
    # T20 Chakrulo — orchestral triumph (false triumph — cold underneath)
    add(BR, pack(theme(BRASS_T20, None, 'ff'),
                 '7/8', ks=-2, bpm=120, txt='Sc.11 — Bull of Heaven | T20 Chakrulo (7/8, ff) — false triumph'))
    add(ST, pack(theme(T20_orch, None, 'ff'), '7/8', ks=-2))
    add(CH, pack(theme(T20_orch, LYR['T20_en'], 'ff'), '7/8', ks=-2))
    # T17 Mravalzhamier — Trio's LAST full harmony
    add(MK, pack(theme(T17_trio, LYR['T17_geo'], 'ff'),
                 '4/4', ks=1, bpm=72, txt='T17 ff — LAST full Trio harmony (this is the last time)'))
    add(MT, pack(theme(T17_trio, LYR['T17_en'], 'ff'), '4/4', ks=1))
    add(BN, pack(theme(T17_trio, None, 'ff'), '4/4', ks=1, cl_str='bass'))
    BN.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('← LAST TIME Trio sings in harmony'))
    # Gilgamesh + Enkidu victory
    add(G, pack(theme([('Bb3',1),('D4',0.5),('F4',0.5),('Bb4',2),('G4',1),('F4',1),('Bb3',2)],
                      LYR['T20_en'][:7], 'ff'), '7/8', ks=-2))
    add(E, pack(theme([('F4',1),('G4',0.5),('Bb4',0.5),('D5',2),('C5',1),('Bb4',1),('F4',2)],
                      LYR['T20_en'][:7], 'ff'), '7/8', ks=-2))
    # Winds: off-beat Chakrulo
    add(WD, pack(theme(T20_orch, None, 'ff'), '7/8', ks=-2))

    fill(NS,'7/8',8); fill(SH,'7/8',8); fill(HU,'7/8',8)
    fill(LM,'7/8',8); fill(CN,'7/8',8); fill(PD,'7/8',8)
    fill(CL,'7/8',8); fill(PI,'7/8',8)

    # ── SCENE 12 — Judgment of Gods (C# minor, ♩=52, a cappella) ──────
    # T14 Shamhat's Curse — the most devastating moment
    add(SH, pack(theme(T14_shamhat, LYR['T14_en'][:18], 'fff'),
                 '4/4', ks=4, bpm=52, txt='Sc.12 — T14 Shamhat\'s Curse | a cappella | fff → silence'))
    SH.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('A5 — sustained scream — then fall to silence'))
    # One measure of absolute silence after the curse
    P['SH'].append(silence_measure('4/4', '(absolute silence — the gods have spoken)'))
    # Chorus: Sumerian judgment voices
    add(CH, pack(theme(T16_chorus, ['Let','it','be!','Let','it','be!','Let','it','be!'],
                       'mf'), '4/4', ks=4, bpm=52))
    # Piano: dissonant cluster
    add(PI, pack(theme(PIANO_T2, None, 'mf'), '4/4', ks=4))

    fill(G,'4/4',8); fill(E,'4/4',8); fill(NS,'4/4',8); fill(HU,'4/4',8)
    fill(MK,'4/4',8); fill(MT,'4/4',8); fill(BN,'4/4',8)
    fill(LM,'4/4',8); fill(CN,'4/4',8); fill(PD,'4/4',8)
    fill(ST,'4/4',8); fill(WD,'4/4',8); fill(BR,'4/4',8); fill(CL,'4/4',8)

    # ── SCENE 13 — Enkidu Dies (D minor, ♩=46) ─────────────────────────
    # T10 Samkurao — Ninsun, last time — pp
    add(NS, pack(theme(T10_ninsun, LYR['T10_geo'][:23], 'pp'),
                 '4/4', ks=-1, bpm=46,
                 txt='Sc.13 — Enkidu\'s Death | T10 Samkurao pp | T6 lamuri pppp→0'))
    # Lamuri: pppp — last breath
    add(LM, pack(theme(T6_lamuri, None, 'pppp', fermata_last=True), '4/4', ks=-1))
    LM.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('LAST NOTE — pppp → 0'))
    # T2 — Trio collapses: voices separate, no longer together
    add(MK, pack(theme(T2_mkrimani, None, 'mf'), '4/4', ks=0))
    add(MT, pack(theme(T2_mtavari, None, 'mf'), '4/4', ks=0))
    add(BN, pack(theme(T2_bani, None, 'mf'), '4/4', ks=0, cl_str='bass'))
    BN.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('Trio fractures — T2'))
    # Cello: grief arc, falls to low D2
    add(CL, pack(theme([('D3',2),('F3',1),('A3',1),('D4',1),('C4',1),('Bb3',2),
                        ('A3',2),('G3',1),('F3',1),('D3',2),('D2',4)],
                       None, 'ppp'), '4/4', ks=-1, cl_str='bass'))

    fill(G,'4/4',8); fill(E,'4/4',8); fill(SH,'4/4',8); fill(HU,'4/4',8)
    fill(CN,'4/4',8); fill(PD,'4/4',8)
    fill(ST,'4/4',8); fill(WD,'4/4',8); fill(BR,'4/4',8); fill(PI,'4/4',8); fill(CH,'4/4',8)


# ══════════════════════════════════════════════════════════════════════
# ACT V — SEARCH FOR IMMORTALITY (~50 min)
# ══════════════════════════════════════════════════════════════════════

def act_V(P):
    G=P['G']; E=P['E']; NS=P['NS']; SH=P['SH']; HU=P['HU']
    MK=P['MK']; MT=P['MT']; BN=P['BN']; CH=P['CH']
    LM=P['LM']; CN=P['CN']; PD=P['PD']
    ST=P['ST']; WD=P['WD']; BR=P['BR']; CL=P['CL']; PI=P['PI']

    # ── SCENE 14 — Gilgamesh's Lament (Atonal, T2 fff) ────────────────
    # T2 fff — maximum chaos — three voices independent, cannot find each other
    add(MK, pack(theme(T2_mkrimani, LYR['T2_mk'], 'fff'),
                 '4/4', ks=0, bpm=88, txt='Sc.14 — Lament | T2 fff | Three voices in chaos — do NOT align'))
    add(MT, pack(theme(T2_mtavari, LYR['T2_mt'], 'fff'), '4/4', ks=0))
    add(BN, pack(theme(T2_bani,    LYR['T2_bn'], 'fff'), '4/4', ks=0, cl_str='bass'))
    # Gilgamesh: accuses the Trio
    add(G, pack(theme([('G3',0.5),('Bb3',0.5),('D4',1),('F4',1),('Eb4',0.5),
                       ('D4',0.5),('R',1),('D4',1),('F4',0.5),('G4',0.5),
                       ('Bb4',1),('A4',0.5),('G4',0.5),('F4',1),('D4',2)],
                      LYR['lament'], 'fff'),
                '4/4', ks=-1, bpm=88, txt='Gilgamesh accuses the Trio — "Who are you?!"'))
    # Piano: dissonant cluster fff
    add(PI, pack(theme(PIANO_T2, None, 'fff'), '4/4', ks=0))
    # Cello: E pedal (abyss)
    add(CL, pack(theme([('E2',4),('E2',4),('E2',4),('E2',4)], None, 'mp'), '4/4', cl_str='bass'))
    # Strings: tense tremolo (no key center)
    add(ST, pack(theme([('G3',0.5),('Ab3',0.5),('G3',0.5),('F#3',0.5),
                        ('G3',2),('F#3',0.5),('G3',0.5),('Ab3',1),('G3',2)], None, 'mf'), '4/4'))

    fill(E,'4/4',8); fill(NS,'4/4',8); fill(SH,'4/4',8); fill(HU,'4/4',8)
    fill(LM,'4/4',8); fill(CN,'4/4',8); fill(PD,'4/4',8); fill(WD,'4/4',8)
    fill(BR,'4/4',8); fill(CH,'4/4',8)

    # ── SCENE 15 — Waters of Death (E pedal, ♩=42, shadows) ───────────
    # Chorus: shadows — Mze Mikhvda fragments
    shadow_notes = [('E4',2),('F#4',1),('G4',1),('A4',2),('G4',1),('F#4',1),
                    ('E4',4),('G4',2),('F#4',1),('E4',1),('D4',2),('E4',2)]
    add(CH, pack(theme(shadow_notes, LYR['shadows'], 'pp'),
                 '4/4', ks=1, bpm=42, txt='Sc.15 — Waters of Death | Shadows choir | E pedal'))
    # Cello: E2 pedal — sustained, massive
    add(CL, pack(theme([('E2',4),('E2',4),('E2',4),('B2',2),('E2',2),
                        ('E2',4),('E2',4)], None, 'mp'), '4/4', ks=1, cl_str='bass'))
    # Gilgamesh: fragments of T1 — broken, barely recognizable
    add(G, pack(theme([('D4',2),('R',1),('F#4',1),('R',1),('A4',1),('G4',2),
                       ('F#4',1),('E4',1),('D4',4)],
                      ['I','seek...','En-','ki-','du...','where?','wher-','e?','are','you?'],
                      'p'), '4/4', ks=1))
    # T2 fragments — Trio still cannot find each other
    add(MK, pack(theme(T2_mkrimani[:5], None, 'pp'), '4/4', ks=0))
    add(MT, pack(theme(T2_mtavari[:5], None, 'pp'), '4/4', ks=0))
    add(BN, pack(theme(T2_bani[:5],   None, 'pp'), '4/4', ks=0, cl_str='bass'))

    fill(E,'4/4',8); fill(NS,'4/4',8); fill(SH,'4/4',8); fill(HU,'4/4',8)
    fill(LM,'4/4',8); fill(CN,'4/4',8); fill(PD,'4/4',8)
    fill(ST,'4/4',8); fill(WD,'4/4',8); fill(BR,'4/4',8); fill(PI,'4/4',8)

    # ── SCENE 16 — Utnapishtim (G major, ♩=54, T3 pp — first healing) ─
    # T7 Nana — Utnapishtim sings the lullaby of the eternal island
    add(HU, pack(theme(T7_ninsun,
                       ['The','flow-','er','grows','at','the','bot-','tom','of','the','sea.',
                        'Find','it.'],
                       'p'), '4/4', ks=1, bpm=54, txt='Sc.16 — Utnapishtim | T7 Iavnana | T3 pp (healing begins)'))
    # T3 pp — the soul BEGINS to find its way back (most tender moment)
    add(MK, pack(theme(T3_mkrimani, LYR['T3_fin'], 'pp'),
                 '4/4', ks=2, bpm=66, txt='T3 pp — Trio begins to heal (D major, tentative)'))
    add(MT, pack(theme(T3_mtavari, LYR['T3_geo'][:11], 'pp'), '4/4', ks=2))
    add(BN, pack(theme(T3_bani, None, 'pp'), '4/4', ks=2, cl_str='bass'))
    BN.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('← Soul begins to knit together'))
    # Gilgamesh finds the flower
    add(G, pack(theme([('G3',1),('B3',0.5),('D4',0.5),('G4',2),('F#4',1),
                       ('E4',1),('D4',1),('C4',1),('B3',1),('G3',2)],
                      ['I','found','it!','The','flow-','er!','I','found','it!','it\'s','mine!','(pause)','gone.'],
                      'mp'), '4/4', ks=1))
    # Lamuri: pppp Svan echo (Enkidu's ghost)
    add(LM, pack(theme(T4_lamuri, None, 'pppp'), '4/4', ks=0,
                 txt='Lamuri: pppp — last Svan echo (Enkidu\'s ghost)'))
    LM.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('Enkidu\'s ghost — pppp'))
    # Strings: warm D major resolution beginning
    add(ST, pack(theme(STR_T1_OSTINATO, None, 'pp'), '4/4', ks=2))

    fill(E,'4/4',8); fill(NS,'4/4',8); fill(SH,'4/4',8)
    fill(CN,'4/4',8); fill(PD,'4/4',8); fill(WD,'4/4',8)
    fill(BR,'4/4',8); fill(CL,'4/4',8); fill(PI,'4/4',8); fill(CH,'4/4',8)

    # ── SCENE 17 — FINALE — ALILO (D major, ♩=88, T3 ff + T11 Lile) ──
    # T3 ff — Trio finally WHOLE — emotional catharsis
    # Build: starts pp (Scene 16), through mp, mf, f, finally fff
    add(MK, pack(theme(T3_mkrimani, LYR['T3_fin'], 'ff'),
                 '4/4', ks=2, bpm=88, txt='Sc.17 — FINALE | T3 ff ALILO | Trio resolved | D major | ♩=88'))
    add(MT, pack(theme(T3_mtavari, LYR['T3_geo'][:11], 'ff'), '4/4', ks=2))
    add(BN, pack(theme(T3_bani, None, 'ff'), '4/4', ks=2, cl_str='bass'))
    BN.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('← TRIO WHOLE — soul resolved at last'))

    # T11 Lile women's choir — three-voice Georgian polyphony
    add(NS, pack(theme(T11_sop1, LYR['T11_en'], 'f'),
                 '4/4', ks=2, bpm=96, txt='T11 Lile — women\'s 3-voice Georgian finale'))
    add(SH, pack(theme(T11_sop2, LYR['T11_en'], 'f'), '4/4', ks=2))
    add(CH, pack(theme(T11_alto, LYR['T11_en'], 'f'), '4/4', ks=2))

    # Full orchestral T3 — climactic
    add(ST, pack(theme(T3_mtavari, None, 'ff'), '4/4', ks=2))
    add(WD, pack(theme(T3_mkrimani, None, 'ff'), '4/4', ks=2))
    add(BR, pack(theme([('D3',1),('A3',0.5),('D4',0.5),('F#4',2),('R',1),
                        ('A2',0.5),('D3',0.5),('F#3',1),('A3',2),('D4',2)], None, 'fff'), '4/4', ks=2))
    add(PI, pack(theme(STR_T1_OSTINATO, None, 'ff'), '4/4', ks=2))

    # Gilgamesh: final solo WITHOUT Trio (he no longer needs them)
    add(G, pack(theme([('D4',2),('R',1),('F#4',1),('R',1),('A4',1),
                       ('D5',2),('R',1),('A4',1),('F#4',1),('D4',1),('R',1),('D3',4)],
                      LYR['gil_alone'], 'p'),
                '4/4', ks=2, bpm=66, txt='Gilgamesh: final solo — WITHOUT Trio (he is whole now)'))
    G.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('Trio falls silent — Gilgamesh is whole'))

    # Enkidu: Lile echo — from offstage
    add(E, pack(theme(T11_alto,
                      ['Li-','le,','li-','le,','En-','ki-','du...','re-','mem-','bered','for-','e-','ver'],
                      'f'), '4/4', ks=2, txt='Enkidu — Lile (echo from offstage, posthumous)'))

    # Cello: final descent D3→D2→0
    add(CL, pack(theme(CELLO_FINAL, None, 'pp'), '4/4', ks=2, cl_str='bass',
                 txt='Cello descends: D3→D2→0 (the opera ends in silence)'))
    CL.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('pppp → 0 — silence'))

    # Lamuri: absolute final note (pppp — the last memory of Enkidu)
    add(LM, pack(theme([('D4',4),('R',4)], None, 'pppp'),
                 '4/4', txt='LAST Svan note — pppp — then nothing'))
    LM.getElementsByClass('Measure')[-1].insert(0,
        expressions.TextExpression('LAMURI: final D4 pppp → 0 — Enkidu is gone'))

    fill(HU,'4/4',8); fill(CN,'4/4',8); fill(PD,'4/4',8)


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def build():
    print('ŠAMNU AZUZI v2 — building score...')
    sc  = stream.Score()
    md  = metadata.Metadata()
    md.title        = 'ŠAMNU AZUZI / სამნუ ა-ზუ-ზი'
    md.composer     = 'Jaba Tkemaladze'
    md.movementName = 'Opera in Five Acts · ~210 min · English/Georgian'
    sc.metadata = md

    P = make_parts()

    print('  Act I  — Tyranny and Solitude (~35 min)...')
    act_I(P)
    print('  Act II — Two Origins Meet (~40 min)...')
    act_II(P)
    print('  Act III — Cedar Forest (~40 min)...')
    act_III(P)
    print('  Act IV — Bull of Heaven and Judgment (~45 min)...')
    act_IV(P)
    print('  Act V  — Search for Immortality (~50 min)...')
    act_V(P)

    for k in ALL_PARTS:
        sc.append(P[k])

    print(f'Writing → {OUT_FILE}')
    sc.write('musicxml', fp=OUT_FILE)
    sz = os.path.getsize(OUT_FILE) // 1024
    print(f'Done. {sz} KB')
    print()
    print('Open: musescore3 SAMNU_AZUZI_v2.musicxml')
    print()
    print('THEMES USED:')
    for t,desc in [
        ('T1','Tsintskaro (harmony) — Trio wholeness, D major'),
        ('T2','Tsintskaro (dissonance) — Trio fracture, atonal'),
        ('T3','Alilo (finale) — Trio resolved, D major'),
        ('T4','Zari pure — Enkidu/Svan, A natural minor'),
        ('T5','Zari transformation — Svan→Racha'),
        ('T6','Virishkhau — Enkidu dying, pppp→0'),
        ('T7','Nana/Iavnana — Ninsun lullaby, D minor'),
        ('T8','Mze Mikhvda — prophecy, D minor→D major'),
        ('T9','Odoia — Megrelian ritual, D aeolian'),
        ('T10','Samkurao — Megrelian lament, D minor'),
        ('T11','Lile/Orovela — women\'s 3-voice finale, D major'),
        ('T12','Mtiuluri — Shamhat entrance, A major 5/8'),
        ('T13','Gandagana — Shamhat+Enkidu duet'),
        ('T14','Shamhat\'s Curse — a cappella soprano fff'),
        ('T15','Khasanbegura — battle, D minor 5/8'),
        ('T16','Beri-Berikoba — citizens chorus, G minor'),
        ('T17','Mravalzhamier — celebration, G major'),
        ('T18','Rekhviashi — Svan men\'s chorus'),
        ('T19','Humbaba\'s theme — chromatic descent, C# minor'),
        ('T20','Chakrulo — Bull of Heaven, Bb major 7/8'),
    ]:
        print(f'  {t}: {desc}')

if __name__ == '__main__':
    build()
