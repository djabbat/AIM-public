#!/usr/bin/env python3
"""
ŠAMNU AZUZI — Генератор MuseScore / MusicXML партитуры
Опера в пяти актах · Джаба Ткемаладзе

Генерирует полный клавир (piano-vocal score) всей оперы:
• Все 17 сцен · 5 актов
• Все вокальные партии с грузинским текстом
• Все 20 тем T1–T20
• Динамика, темп, тональности, тактовые размеры
• Световые и сценические ремарки (текстовые метки)
"""

import os
from music21 import (
    stream, note, chord, tempo, meter, key, dynamics,
    expressions, layout, metadata, instrument,
    clef, bar, text, repeat
)
from music21.note import Rest
from music21.tempo import MetronomeMark

OUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "SAMNU_AZUZI_Full_Score.musicxml")

# ─── helpers ────────────────────────────────────────────────────────────────

def N(pitch, dur=1.0, dyn=None, lyric=None, slur_start=False, slur_end=False):
    """Create a Note. dur in quarter lengths."""
    n = note.Note(pitch, quarterLength=dur)
    if lyric:
        n.addLyric(lyric)
    if dyn:
        d = dynamics.Dynamic(dyn)
        n.expressions.append(d)
    return n

def R(dur=1.0):
    """Create a Rest."""
    return Rest(quarterLength=dur)

def notes(pitches, dur=1.0, lyrics=None, dyn=None):
    """List of notes from pitch strings."""
    lyr = lyrics or [None] * len(pitches)
    result = []
    for i, p in enumerate(pitches):
        if p == 'R':
            result.append(R(dur))
        else:
            l = lyr[i] if i < len(lyr) else None
            d = dyn if i == 0 else None
            result.append(N(p, dur, dyn=d, lyric=l))
    return result

def add_tempo(s, bpm, text_mark=""):
    mm = MetronomeMark(number=bpm, text=text_mark)
    s.append(mm)

def add_rehearsal(s, label):
    """Add rehearsal mark / section label."""
    rm = expressions.RehearsalMark(label)
    s.append(rm)

def add_text(s, txt):
    """Add text expression."""
    te = expressions.TextExpression(txt)
    s.append(te)

def make_measure(elements, ts=None, ks=None, clef_obj=None):
    """Create a Measure with optional time/key signature and elements."""
    m = stream.Measure()
    if clef_obj:
        m.append(clef_obj)
    if ks:
        m.append(ks)
    if ts:
        m.append(ts)
    for el in elements:
        m.append(el)
    return m

def part(name, abbr, instr=None):
    """Create a Part with instrument name."""
    p = stream.Part()
    p.partName = name
    p.partAbbreviation = abbr
    if instr:
        p.insert(0, instr)
    return p

# ─── SCORE STRUCTURE ────────────────────────────────────────────────────────

def build_score():
    sc = stream.Score()

    # Metadata
    md = metadata.Metadata()
    md.title = "Samnu Azuzi"
    md.composer = "Jaba Tkemaladze"
    md.copyright = "2026"
    sc.insert(0, md)

    # ── PARTS ────────────────────────────────────────────────────────────
    p_gil  = part("Gilgamesh",  "Gil.", instrument.Baritone())
    p_enc  = part("Enkidu",     "Enc.", instrument.Tenor())
    p_nin  = part("Ninsun",     "Nin.", instrument.MezzoSoprano())
    p_sha  = part("Shamhat",    "Sha.", instrument.Soprano())
    p_hum  = part("Humbaba",    "Hum.", instrument.Bass())
    p_utn  = part("Utnapishtim","Utn.", instrument.Baritone())
    p_mk   = part("Mkrimani",   "Mk.",  instrument.Tenor())
    p_mt   = part("Mtavari",    "Mt.",  instrument.Tenor())
    p_ba   = part("Bani",       "Ba.",  instrument.Bass())
    p_chor = part("Choir",      "Ch.",  instrument.Vocalist())
    p_lam  = part("Lamuri",     "Lam.", instrument.Flute())
    p_chu  = part("Chuniri",    "Chu.", instrument.Violin())
    p_pan  = part("Panduri",    "Pan.", instrument.Vocalist())
    p_pno  = part("Piano (reduction)", "Pno.", instrument.Piano())

    all_parts = [p_gil, p_enc, p_nin, p_sha, p_hum, p_utn,
                 p_mk,  p_mt,  p_ba,
                 p_chor, p_lam, p_chu, p_pan, p_pno]

    # ════════════════════════════════════════════════════════════════════
    # ACT I — "TYRANNY AND SOLITUDE"
    # ════════════════════════════════════════════════════════════════════

    # ── SCENE 1 — Uruk in Lament ─────────────────────────────────────
    # T16 Beri-Berikoba · G minor · 5/8 · q.=58
    # + T1 Trio pp

    ks1 = key.Key('g')
    ts1 = meter.TimeSignature('5/8')
    mm1 = MetronomeMark(number=58, text="Allegro giocoso")

    # Choir — T16 Beri-Berikoba
    m = stream.Measure(number=1)
    m.append(ks1)
    m.append(ts1)
    m.append(mm1)
    add_rehearsal(m, "ACT I · Sc.1: Uruki (T16)")
    add_text(m, "Uruki - goroda plach. Utrenniy svet.")
    p_chor.append(m)

    # T16 main phrase (G minor 5/8) — 4 measures
    T16_pitches = [
        ['G4','B-4','D5','C5','B-4'],
        ['A4','G4','F#4','G4','R'],
        ['G4','B-4','D5','C5','B-4'],
        ['A4','G4','F#4','G4','R'],
    ]
    T16_lyr = [
        ['U-', 'ru-', 'qi', 'glo-', 'vobs'],
        ['me-', 'pe', 'ar', 'gves-', None],
        ['mis!', None, None, None, None],
        [None, None, None, None, None],
    ]
    for i, (pitches_row, lyr_row) in enumerate(zip(T16_pitches, T16_lyr)):
        m = stream.Measure(number=2+i)
        for j, p_str in enumerate(pitches_row):
            if p_str == 'R':
                m.append(R(0.5))
            else:
                n = N(p_str, 0.5)
                if j < len(lyr_row) and lyr_row[j]:
                    n.addLyric(lyr_row[j])
                if j == 0 and i == 0:
                    n.expressions.append(dynamics.Dynamic('mf'))
                m.append(n)
        p_chor.append(m)

    # Trio T1 pp (appearing in shadow) — Mkrimani, Mtavari, Bani
    ks1g = key.Key('d')
    ts1g = meter.TimeSignature('4/4')
    mm1g = MetronomeMark(number=72, text="Andante moderato")

    for p_trio, pitches_trio, dyn_val in [
        (p_mk, ['D5','F#5','A5','G5','F#5','E5','D5','C#5','D5'], 'pp'),
        (p_mt, ['A4','D5','F#5','E5','D5','C#5','D4','B3','A4'], 'pp'),
        (p_ba, ['D3','A3','D4','A3','D3','A2','D3','A2','D3'], 'pp'),
    ]:
        m = stream.Measure(number=1)
        m.append(ks1g)
        m.append(ts1g)
        m.append(mm1g)
        add_text(m, "Trio — v teni, ppp (gorozhdane ne slyshat)")
        if p_trio == p_ba:
            m.append(clef.BassClef())
        p_trio.append(m)
        for i in range(0, len(pitches_trio), 4):
            chunk = pitches_trio[i:i+4]
            m2 = stream.Measure(number=2 + i//4)
            for j, p_str in enumerate(chunk):
                n = N(p_str, 1.0)
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(dyn_val))
                m2.append(n)
            p_trio.append(m2)

    # Fill other parts with rests for Sc.1
    for p_part in [p_gil, p_enc, p_nin, p_sha, p_hum, p_utn, p_lam, p_chu, p_pan]:
        m = stream.Measure(number=1)
        m.append(ks1)
        m.append(ts1)
        m.append(R(2.5))  # full 5/8 rest
        p_part.append(m)
        for i in range(3):
            m2 = stream.Measure(number=2+i)
            m2.append(R(2.5))
            p_part.append(m2)

    # Piano reduction — T16 bass line
    m = stream.Measure(number=1)
    m.append(key.Key('g'))
    m.append(meter.TimeSignature('5/8'))
    m.append(MetronomeMark(number=58))
    p_pno.append(m)
    for i in range(3):
        m2 = stream.Measure(number=2+i)
        m2.append(N('G2', 2.5))
        p_pno.append(m2)

    # ── SCENE 2 — Three Dreams ───────────────────────────────────────
    # T7 Nana (Ninsun) + T8 Mze Mikhvda + T1 ff (Trio)
    # D minor · ♩=60

    measure_offset = 6

    ks2 = key.Key('d', 'minor')
    ts2 = meter.TimeSignature('3/4')
    mm2_nana = MetronomeMark(number=60, text="Andante dolce")

    # Rehearsal mark
    m = stream.Measure(number=measure_offset)
    m.append(ks2)
    m.append(ts2)
    add_rehearsal(m, "Sc.2: Three Dreams")
    add_text(m, "Pokoi Gilgamesha. Noch. Ninsun u lozha.")
    m.append(R(3.0))
    p_nin.append(m)

    # T7 Nana — Ninsun sings
    T7_pitches = ['D4','F4','E4','D4','C4','D4','F4','G4','A4','G4','F4','E4','D4']
    T7_lyr     = ['na-','na,','na-','na,','shvi-','li','chqi-','ri-','me,','na-','na,','ia-','o']
    for i in range(0, len(T7_pitches), 3):
        chunk = T7_pitches[i:i+3]
        ll    = T7_lyr[i:i+3]
        m = stream.Measure(number=measure_offset+1 + i//3)
        m.append(ks2)
        m.append(ts2)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 1.0)
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('p'))
            m.append(n)
        p_nin.append(m)

    # T8 Mze Mikhvda — prophecy
    mm2_mze = MetronomeMark(number=50, text="Largo maestoso")
    T8_pitches = ['A4','C5','B4','A4','G4','F4','E4','D4',
                  'F4','A4','C5','B4','A4','G4','F4','E4','D4']
    m_start = measure_offset + 6
    m = stream.Measure(number=m_start)
    m.append(key.Key('d', 'minor'))
    m.append(meter.TimeSignature('4/4'))
    m.append(mm2_mze)
    add_text(m, "T8: Mze Mikhvda — prorochestvo")
    m.append(R(4.0))
    p_nin.append(m)
    for i in range(0, len(T8_pitches), 4):
        chunk = T8_pitches[i:i+4]
        m2 = stream.Measure(number=m_start+1+i//4)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 1.0)
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('mp'))
            elif i == 8 and j == 0:
                n.expressions.append(dynamics.Dynamic('f'))
            m2.append(n)
        p_nin.append(m2)

    # Trio — T1 full (D major, ff)
    T1_mk = ['D5','F#5','A5','G5','F#5','E5','D5','C#5','D5']
    T1_mt = ['A4','D5','F#5','E5','D5','C#5','D4','B3','A4']
    T1_ba = ['D3','A3','D4','A3','D3','A2','D3','A2','D3']
    mm2_t1 = MetronomeMark(number=72, text="Andante moderato")

    for p_trio, pts, dyn_v in [(p_mk,T1_mk,'ff'),(p_mt,T1_mt,'f'),(p_ba,T1_ba,'mf')]:
        m = stream.Measure(number=measure_offset)
        m.append(key.Key('d'))
        m.append(meter.TimeSignature('4/4'))
        m.append(mm2_t1)
        add_text(m, "Trio — T1 ff (perviy raz v polnuyu silu)")
        if p_trio == p_ba:
            m.append(clef.BassClef())
        p_trio.append(m)
        for i in range(0, len(pts), 4):
            chunk = pts[i:i+4]
            m2 = stream.Measure(number=measure_offset+1+i//4)
            for j, p_str in enumerate(chunk):
                n = N(p_str, 1.0)
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(dyn_v))
                m2.append(n)
            p_trio.append(m2)

    # Gilgamesh — reacts to dreams
    m = stream.Measure(number=measure_offset)
    m.append(ks2)
    m.append(ts2)
    add_text(m, "Gilgamesh rasskazyvaet sny Ninsun")
    m.append(R(3.0))
    p_gil.append(m)
    # Simple recitative-style
    dream_pitches = [
        (['A3','C4','D4'], ['Son','per-','viy:']),
        (['F4','E4','D4'], ['zhez-','l-', 'ya!']),
        (['A4','G4','F4'], ['Son','vto-','roy:']),
        (['E4','D4','C4'], ['to-', 'por','pyal!']),
    ]
    for i, (dp, dl) in enumerate(dream_pitches):
        m2 = stream.Measure(number=measure_offset+1+i)
        for j, (p_str, lw) in enumerate(zip(dp, dl)):
            n = N(p_str, 1.0)
            n.addLyric(lw)
            if j == 0:
                n.expressions.append(dynamics.Dynamic('mf'))
            m2.append(n)
        p_gil.append(m2)

    # ── SCENE 3 — Creation of Enkidu ────────────────────────────────
    # T4 Zari (pure) — Lamuri · A minor · senza misura
    # + T18-style Lile choir (bass drone)

    scene3_offset = measure_offset + 14

    ks3 = key.Key('a', 'minor')
    ts3 = meter.TimeSignature('4/4')
    mm3 = MetronomeMark(number=52, text="Senza misura, rubato")

    # Lamuri — T4 pure
    T4_pitches = ['D4','E4','G4','A4','G4','E4','D4',
                  'G4','A4','C5','D5','C5','A4','G4']
    T4_lyr = ['vi-','ri-','shk-','hau',None,None,None,
              'la-','mu-','ri',None,None,None,None]

    m = stream.Measure(number=scene3_offset)
    m.append(ks3)
    m.append(ts3)
    m.append(mm3)
    add_rehearsal(m, "Sc.3: Sotvoreniye Enkidu (T4)")
    add_text(m, "Step. Gazeli. Aruru lepit Enkidu. Lamuri za stseny.")
    m.append(R(4.0))
    p_lam.append(m)

    for i in range(0, len(T4_pitches), 4):
        chunk = T4_pitches[i:i+4]
        ll    = T4_lyr[i:i+4]
        m2 = stream.Measure(number=scene3_offset+1+i//4)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 1.5)  # long, rubato
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('p'))
            m2.append(n)
        p_lam.append(m2)

    # Enkidu first appearance — vocal on A4 (birth cry)
    m = stream.Measure(number=scene3_offset + 5)
    m.append(ks3)
    m.append(ts3)
    add_text(m, "Enkidu poyavlyaetsya. Perviy zvuk.")
    en = N('A4', 4.0)
    en.addLyric("A-a-a...")
    en.expressions.append(dynamics.Dynamic('mf'))
    m.append(en)
    p_enc.append(m)

    # Bass choir drone — Svan Lile (primitive unison D)
    m = stream.Measure(number=scene3_offset)
    m.append(ks3)
    m.append(ts3)
    add_text(m, "Niz. golosa: 'Lile' — golos zemli (unison)")
    m.append(N('D3', 4.0, dyn='pp'))
    p_chor.append(m)
    for i in range(3):
        m2 = stream.Measure(number=scene3_offset+1+i)
        m2.append(N('D3', 4.0))
        p_chor.append(m2)

    # ════════════════════════════════════════════════════════════════════
    # ACT II — "MEETING OF TWO BEGINNINGS"
    # ════════════════════════════════════════════════════════════════════

    act2_offset = scene3_offset + 10

    # ── SCENE 4 — Shamhat at the Spring ─────────────────────────────
    # T12 Mtiuluri (Shamhat) vs T4 fading (Enkidu) · A major/minor · 5/8

    ks4 = key.Key('A')
    ts4 = meter.TimeSignature('5/8')
    mm4 = MetronomeMark(number=60, text="Allegro con fuoco")

    T12_pitches = ['A4','B4','C5','B4','A4','G4','A4','B4','C5','A4',
                   'C5','D5','E5','D5','C5','B4','C5','D5','E5','C5']
    T12_lyr =     ['mti-','u-','lu-','ri,','mti-','u-','lu-','ri,','tsek-','vavs',
                   'gu-','li,','tsek-','vavs','sis-','khli!',None,None,None,None]

    m = stream.Measure(number=act2_offset)
    m.append(ks4)
    m.append(ts4)
    m.append(mm4)
    add_rehearsal(m, "ACT II · Sc.4: Shamhat (T12 Mtiuluri)")
    add_text(m, "Lesnoy istochnik. Vecher. Shamhat tantsuyot.")
    m.append(R(2.5))
    p_sha.append(m)

    for i in range(0, len(T12_pitches), 5):
        chunk = T12_pitches[i:i+5]
        ll    = T12_lyr[i:i+5]
        m2 = stream.Measure(number=act2_offset+1+i//5)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 0.5)
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('mf'))
            m2.append(n)
        p_sha.append(m2)

    # Enkidu — T4 fading (A minor, conflicted)
    m = stream.Measure(number=act2_offset)
    m.append(key.Key('a', 'minor'))
    m.append(ts4)
    add_text(m, "Enkidu vidyt Shamhat — pervyy moment 'zarazheniya'")
    m.append(R(2.5))
    p_enc.append(m)
    for i, p_str in enumerate(['A4','G4','E4','D4','C4','D4','E4','G4','A4','B4']):
        if i % 5 == 0:
            m2 = stream.Measure(number=act2_offset+1+i//5)
            p_enc.append(m2)
        n = N(p_str, 0.5)
        if i == 0:
            n.expressions.append(dynamics.Dynamic('p'))
        m2.append(n)

    # ── SCENE 5 — Seven Days (T5 — 7 variations) ────────────────────
    sc5_offset = act2_offset + 6

    ks5a = key.Key('a', 'minor')
    ks5b = key.Key('A')
    ts5  = meter.TimeSignature('4/4')

    for var_num in range(1, 8):
        var_offset = sc5_offset + (var_num-1)*3
        ks_var = ks5a if var_num <= 4 else ks5b
        # Lamuri (fading each var)
        dyn_map = {1:'f',2:'mf',3:'mf',4:'mp',5:'p',6:'pp',7:'ppp'}
        m = stream.Measure(number=var_offset)
        m.append(ks_var)
        m.append(ts5)
        if var_num == 1:
            m.append(MetronomeMark(number=80, text="Moderato — 7 variaziy"))
            add_rehearsal(m, "Sc.5: Sem Dney (T5)")
        add_text(m, f"Variatsiya {var_num}/7 — {'Enkidu teryayet svan elem' if var_num > 4 else 'Svan elem sokhryanyaetsya'}")
        m.append(R(4.0))
        p_lam.append(m)

        # T5 lamuri line — each variation shifts up a semitone (transformation)
        shift = var_num - 1
        T5_base = ['D4','E4','G4','A4','B4','A4','G4','F#4','E4','D4']
        for i in range(0, len(T5_base), 4):
            chunk = T5_base[i:i+4]
            m2 = stream.Measure(number=var_offset+1+i//4)
            for j, p_str in enumerate(chunk):
                if p_str == 'R':
                    m2.append(R(1.0))
                else:
                    n = note.Note(p_str, quarterLength=1.0)
                    n.pitch.transpose(shift, inPlace=True)
                    if i == 0 and j == 0:
                        n.expressions.append(dynamics.Dynamic(dyn_map[var_num]))
                    m2.append(n)
            p_lam.append(m2)

        # Panduri (Shamhat) enters each variation more strongly
        pan_dyn = {1:'p',2:'p',3:'mp',4:'mp',5:'mf',6:'f',7:'ff'}
        T5_pan = ['A4','B4','C5','D5','E5','D5','C5','B4','A4','G4','A4']
        m = stream.Measure(number=var_offset)
        m.append(ks_var)
        m.append(ts5)
        m.append(R(4.0))
        p_pan.append(m)
        for i in range(0, len(T5_pan)-1, 4):
            chunk = T5_pan[i:i+4]
            m2 = stream.Measure(number=var_offset+1+i//4)
            for j, p_str in enumerate(chunk):
                n = N(p_str, 1.0)
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(pan_dyn[var_num]))
                m2.append(n)
            p_pan.append(m2)

    # ── SCENE 6 — Duel (T15 Khasanbegura) ───────────────────────────
    sc6_offset = sc5_offset + 22

    ks6 = key.Key('d', 'minor')
    ts6 = meter.TimeSignature('5/8')
    mm6 = MetronomeMark(number=66, text="Allegro marziale")

    T15_pitches = ['D4','F#4','A4','D5','C5','B4','A4','G4','F#4','E4','D4']

    m = stream.Measure(number=sc6_offset)
    m.append(ks6)
    m.append(ts6)
    m.append(mm6)
    add_rehearsal(m, "Sc.6: Poyedinok (T15 Khasanbegura)")
    add_text(m, "Vorota Uruka. Svadba. Enkidu blokiruyet prokhod.")
    m.append(R(2.5))
    p_pno.append(m)

    for i in range(0, len(T15_pitches), 5):
        chunk = T15_pitches[i:i+5]
        m2 = stream.Measure(number=sc6_offset+1+i//5)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 0.5)
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('f'))
            m2.append(n)
        p_pno.append(m2)

    # Gilgamesh vs Enkidu duet-battle
    m = stream.Measure(number=sc6_offset)
    m.append(ks6)
    m.append(ts6)
    add_text(m, "Gilgamesh vykhodit — bariton vs tenor")
    m.append(R(2.5))
    p_gil.append(m)
    for p_str, lyr_w in [('D4','Gil-'),('F4','ga-'),('A4','mesh!'),('C5','Vstat!'),('B-4','Sto-')]:
        if not hasattr(p_gil, '_sc6_m'):
            m2 = stream.Measure(number=sc6_offset+1)
            p_gil._sc6_m = m2
            p_gil.append(m2)
        else:
            pass
        n = N(p_str, 0.5)
        n.addLyric(lyr_w)
        p_gil._sc6_m.append(n)

    m = stream.Measure(number=sc6_offset)
    m.append(key.Key('d', 'minor'))
    m.append(ts6)
    m.append(R(2.5))
    p_enc.append(m)
    m2 = stream.Measure(number=sc6_offset+1)
    for p_str, lyr_w in [('A4','En-'),('G4','ki-'),('E4','du!'),('D4','Net!'),('C4','Sto-')]:
        n = N(p_str, 0.5)
        n.addLyric(lyr_w)
        m2.append(n)
    p_enc.append(m2)

    # ── SCENE 7 — Brotherhood (T17+T18) ─────────────────────────────
    sc7_offset = sc6_offset + 6

    ks7 = key.Key('G')
    ts7 = meter.TimeSignature('4/4')
    mm7 = MetronomeMark(number=72, text="Andante festivo")

    # T18 Rekhviashi (men)
    T18_pitches = ['D4','E4','G4','A4','C5','A4','G4','E4','D4']
    T18_lyr =     ['rekh-','vi-','ash,','rekh-','vi-','ash,','maq-','val','kh!']

    m = stream.Measure(number=sc7_offset)
    m.append(ks7)
    m.append(ts7)
    m.append(mm7)
    add_rehearsal(m, "Sc.7: Bratstvo — T18+T17")
    add_text(m, "Uruk. Pir. Kliatva bratstva. T18 Rekhviashi → T17 Mravalzhamier")
    m.append(R(4.0))
    p_chor.append(m)

    for i in range(0, len(T18_pitches), 4):
        chunk = T18_pitches[i:i+4]
        ll    = T18_lyr[i:i+4]
        m2 = stream.Measure(number=sc7_offset+1+i//4)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 1.0)
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('mf'))
            m2.append(n)
        p_chor.append(m2)

    # T17 Mravalzhamier — Trio + Choir ff
    T17_pitches = ['G4','B4','D5','G5','F#5','E5','D5','C5','B4','A4','G4']
    T17_lyr =     ['mra-','val-','zha-','mi-','er,','mra-','val-','zha-','mi-','er,','!']

    mm17 = MetronomeMark(number=72, text="Andante festivo — T17 ff")
    for p_part, pts, dyn_v in [
        (p_mk, ['D5','F#5','G5','A5','G5','F#5','E5','D5','C#5','D5','A5'], 'ff'),
        (p_mt, ['G4','B4','D5','G5','F#5','E5','D5','C5','B4','A4','G4'], 'ff'),
        (p_ba, ['G3','B3','D4','G4','F#4','E4','D4','C4','B3','A3','G3'], 'ff'),
    ]:
        m = stream.Measure(number=sc7_offset + 4)
        m.append(ks7)
        m.append(ts7)
        m.append(mm17)
        if p_part == p_ba:
            m.append(clef.BassClef())
        p_part.append(m)
        for i in range(0, len(pts), 4):
            chunk = pts[i:i+4]
            ll    = T17_lyr[i:i+4]
            m2 = stream.Measure(number=sc7_offset+5+i//4)
            for j, p_str in enumerate(chunk):
                n = N(p_str, 1.0)
                if j < len(ll) and ll[j]:
                    n.addLyric(ll[j])
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(dyn_v))
                m2.append(n)
            p_part.append(m2)

    # ════════════════════════════════════════════════════════════════════
    # ACT III — "THE CEDAR FOREST"
    # ════════════════════════════════════════════════════════════════════

    act3_offset = sc7_offset + 16

    # ── SCENE 8 — Ninsun's Blessing (T9 + T10) ──────────────────────
    ks8 = key.Key('d', 'minor')
    ts8 = meter.TimeSignature('4/4')
    mm8 = MetronomeMark(number=70, text="Moderato religioso")

    T9_pitches = ['D4','F4','E4','D4','C4','D4',
                  'F4','G4','A4','G4','F4','E4','D4',
                  'A4','C5','B4','A4','G4','F4','E4','D4']
    T9_lyr =     ['o-','do-','ia,','o-','do-','ia,',
                  'gza','ga-','gi-','mar-','tlos,','shvi-','le-',
                  'bo!','o-','do-','ia,','o-','do-','ia...']

    m = stream.Measure(number=act3_offset)
    m.append(ks8)
    m.append(ts8)
    m.append(mm8)
    add_rehearsal(m, "ACT III · Sc.8: Ninsun (T9 Odoia)")
    add_text(m, "Khram Ninsun. Rassvet. Chuniri solo + arfa. Ninsun u altarya.")
    m.append(R(4.0))
    p_nin.append(m)

    for i in range(0, len(T9_pitches), 4):
        chunk = T9_pitches[i:i+4]
        ll    = T9_lyr[i:i+4]
        m2 = stream.Measure(number=act3_offset+1+i//4)
        for j, p_str in enumerate(chunk):
            if p_str == 'R':
                m2.append(R(1.0))
            else:
                n = N(p_str, 1.0)
                if j < len(ll) and ll[j]:
                    n.addLyric(ll[j])
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic('p'))
                m2.append(n)
        p_nin.append(m2)

    # T10 Samkurao — deeper, slower
    mm10 = MetronomeMark(number=46, text="Lento doloroso — T10 Samkurao")
    T10_pitches = ['D4','F4','E4','D4','C4','D4',
                   'F4','G4','A4','G4','F4','E4','D4',
                   'A4','C5','B4','A4','G4','F4','E4','D4','C4','D4']
    T10_lyr =     ['sam-','ku-','ra-','o,','sam-','ku-',
                   'ra-','o,','chqi-','mi','chqvi-','de,','sam-',
                   'ku-','ra-','o.','tsa-','di,','shvi-','lo,','gza','she-','ni-','a.']

    m = stream.Measure(number=act3_offset + 7)
    m.append(ks8)
    m.append(ts8)
    m.append(mm10)
    add_text(m, "T10 Samkurao — Ninsun: proshanius s synom")
    m.append(R(4.0))
    p_nin.append(m)

    for i in range(0, len(T10_pitches), 4):
        chunk = T10_pitches[i:i+4]
        ll    = T10_lyr[i:i+4]
        m2 = stream.Measure(number=act3_offset+8+i//4)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 1.0)
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('p'))
            m2.append(n)
        p_nin.append(m2)

    # Chuniri accompaniment
    m = stream.Measure(number=act3_offset)
    m.append(ks8)
    m.append(ts8)
    m.append(mm8)
    add_text(m, "Chuniri (violin) solo")
    m.append(R(4.0))
    p_chu.append(m)
    for i in range(0, len(T9_pitches), 4):
        chunk = T9_pitches[i:i+4]
        m2 = stream.Measure(number=act3_offset+1+i//4)
        for p_str in chunk:
            if p_str != 'R':
                m2.append(N(p_str, 1.0, dyn='p' if i==0 else None))
            else:
                m2.append(R(1.0))
        p_chu.append(m2)

    # ── SCENE 9 — March to Cedar Forest (T18+T15 counterpoint) ──────
    sc9_offset = act3_offset + 16

    ks9 = key.Key('e', 'minor')
    ts9 = meter.TimeSignature('4/4')
    mm9 = MetronomeMark(number=66, text="Moderato maestoso — T18+T15 kontrapunkt")

    m = stream.Measure(number=sc9_offset)
    m.append(ks9)
    m.append(ts9)
    m.append(mm9)
    add_rehearsal(m, "Sc.9: Pokhod na Kedr les (T18+T15)")
    add_text(m, "Doroga. T18 Rekhviashi (Svan) vs T15 Khasanbeg (Gur) — kontrapunkt")
    m.append(R(4.0))
    p_chor.append(m)

    # Men's choir T18
    T18_march = ['D4','E4','G4','A4','C5','A4','G4','E4','D4','E4','G4','A4']
    for i in range(0, len(T18_march), 4):
        chunk = T18_march[i:i+4]
        m2 = stream.Measure(number=sc9_offset+1+i//4)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 1.0)
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('mf'))
            m2.append(n)
        p_chor.append(m2)

    # Lamuri — T4 fragment (fading)
    m = stream.Measure(number=sc9_offset)
    m.append(ks9)
    m.append(ts9)
    add_text(m, "Lamuri — T4 fragment (ugasayet)")
    m.append(R(4.0))
    p_lam.append(m)
    for p_str in ['D4','E4','G4','A4','G4','E4','D4','R']:
        if not hasattr(p_lam, '_march_m'):
            m2 = stream.Measure(number=sc9_offset+1)
            p_lam._march_m = m2
            p_lam.append(m2)
        n = N(p_str, 1.0) if p_str != 'R' else R(1.0)
        if p_str == 'D4':
            n.expressions.append(dynamics.Dynamic('mp'))
        p_lam._march_m.append(n)

    # Forest spirits warning — men's choir offstage pp
    m = stream.Measure(number=sc9_offset + 5)
    m.append(ks9)
    m.append(ts9)
    add_text(m, "Dukhi lesa — muzhskoy khor za stseny pp: 'Gada-a-a!'")
    m.append(R(4.0))
    p_chor.append(m)
    spirit_pitches = ['E3','G3','A3','B3','A3','G3','E3','D3']
    for i in range(0, len(spirit_pitches), 4):
        m2 = stream.Measure(number=sc9_offset+6+i//4)
        for j, p_str in enumerate(spirit_pitches[i:i+4]):
            n = N(p_str, 1.0)
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('pp'))
                n.addLyric('Ga-')
            elif i == 0 and j == 1:
                n.addLyric('da-')
            elif i == 0 and j == 2:
                n.addLyric('a-')
            elif i == 0 and j == 3:
                n.addLyric('a!')
            m2.append(n)
        p_chor.append(m2)

    # ── SCENE 10 — Humbaba (T19) ─────────────────────────────────────
    sc10_offset = sc9_offset + 10

    ks10 = key.Key('c#', 'minor')
    ts10 = meter.TimeSignature('4/4')
    mm10_h = MetronomeMark(number=40, text="Lento lugubre — T19 Humbaba")

    T19_pitches = ['D4','C#4','C4','B3','B-3','A3','A-3','G3','F#3','F3','E3','E-3','D3']
    T19_lyr =     ['me','var','tqe.','me','var','ke-','da-','ri.','me','var','kva','kva-','ze.']

    m = stream.Measure(number=sc10_offset)
    m.append(ks10)
    m.append(ts10)
    m.append(mm10_h)
    add_rehearsal(m, "Sc.10: Humbaba (T19 khrom. spusk)")
    add_text(m, "Serdtse Kedrovogo lesa. Humbaba — skulpturnaya konstruktsiya.")
    m.append(R(4.0))
    p_hum.append(m)
    p_hum.append(clef.BassClef())  # Humbaba = bass-profundo

    for i in range(0, len(T19_pitches), 4):
        chunk = T19_pitches[i:i+4]
        ll    = T19_lyr[i:i+4]
        m2 = stream.Measure(number=sc10_offset+1+i//4)
        m2.append(clef.BassClef())
        for j, p_str in enumerate(chunk):
            n = N(p_str, 2.0)  # held notes
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('mf'))
            m2.append(n)
        p_hum.append(m2)

    # Canon offstage pppp
    m = stream.Measure(number=sc10_offset + 2)  # delayed
    m.append(ks10)
    m.append(ts10)
    add_text(m, "Khor derevyev — kanon toy zhe temy pppp za stseny")
    m.append(R(4.0))
    p_chor.append(m)
    for i in range(0, len(T19_pitches)-2, 4):
        chunk = T19_pitches[i:i+4]
        m2 = stream.Measure(number=sc10_offset+3+i//4)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 2.0)
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('pppp'))
            m2.append(n)
        p_chor.append(m2)

    # Lamuri — D4 last note → silence
    m = stream.Measure(number=sc10_offset + 6)
    m.append(ks10)
    m.append(ts10)
    add_text(m, "LAMURI: D4 — posledny zvuk — pppp → 0 (Enkidu otchuzhdaetsya ot prirody)")
    lam_death = N('D4', 4.0)
    lam_death.expressions.append(dynamics.Dynamic('pppp'))
    m.append(lam_death)
    p_lam.append(m)
    m2 = stream.Measure(number=sc10_offset+7)
    m2.append(R(4.0))
    m2.append(bar.Barline('final'))
    p_lam.append(m2)

    # ════════════════════════════════════════════════════════════════════
    # ACT IV — "BULL OF HEAVEN AND JUDGMENT"
    # ════════════════════════════════════════════════════════════════════

    act4_offset = sc10_offset + 12

    # ── SCENE 11 — Ishtar + Bull of Heaven (T20 + T17) ──────────────
    ks11 = key.Key('B-')
    ts11 = meter.TimeSignature('7/8')
    mm11 = MetronomeMark(number=120, text="Allegro eroico — T20 Chakrulo")

    T20_pitches = ['B-4','C5','D5','E-5','F5','G5','F5','E-5','D5','C5','B-4']

    m = stream.Measure(number=act4_offset)
    m.append(ks11)
    m.append(ts11)
    m.append(mm11)
    add_rehearsal(m, "ACT IV · Sc.11: Bull of Heaven (T20 Chakrulo)")
    add_text(m, "Uruk. Steny. Lozniy triumf. Ishtar — pantomima, buto. T20 ff.")
    m.append(R(3.5))
    p_pno.append(m)

    for i in range(0, len(T20_pitches), 7):
        chunk = T20_pitches[i:i+7]
        m2 = stream.Measure(number=act4_offset+1+i//7)
        for j, p_str in enumerate(chunk[:7]):
            n = N(p_str, 0.5)
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('ff'))
            m2.append(n)
        p_pno.append(m2)

    # T17 Mravalzhamier — Trio LAST harmony
    mm17b = MetronomeMark(number=72, text="T17 ff — Trio posledniy raz v garmonii")
    for p_t, pts_t, dyn_t in [
        (p_mk, ['D5','F#5','A5','G5','F#5','E5','D5','C#5','D5'], 'ff'),
        (p_mt, ['G4','B4','D5','G5','F#5','E5','D5','C5','B4'], 'ff'),
        (p_ba, ['G3','B3','D4','G4','F#4','E4','D4','C4','B3'], 'ff'),
    ]:
        m = stream.Measure(number=act4_offset + 3)
        m.append(key.Key('G'))
        m.append(meter.TimeSignature('4/4'))
        m.append(mm17b)
        add_text(m, "T17 Mravalzhamier — POSLENIY RAZ V GARMONII")
        if p_t == p_ba:
            m.append(clef.BassClef())
        p_t.append(m)
        for i in range(0, len(pts_t), 4):
            chunk = pts_t[i:i+4]
            m2 = stream.Measure(number=act4_offset+4+i//4)
            for j, p_str in enumerate(chunk):
                n = N(p_str, 1.0)
                n.addLyric('mra-' if j == 0 else ('val-' if j == 1 else ('zha-' if j == 2 else 'mi-')))
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(dyn_t))
                m2.append(n)
            p_t.append(m2)

    # Gilgamesh + Enkidu triumph
    m = stream.Measure(number=act4_offset)
    m.append(ks11)
    m.append(ts11)
    m.append(R(3.5))
    p_gil.append(m)
    m2 = stream.Measure(number=act4_offset+1)
    for p_str, lyr_w in [('B-4','ga-'),('D5','mar-'),('F5','zhve-'),('B-4','ba!'),('D5','kha-'),('F5','ri'),('B-5','!')]:
        n = N(p_str, 0.5)
        n.addLyric(lyr_w)
        if lyr_w == 'ga-':
            n.expressions.append(dynamics.Dynamic('ff'))
        m2.append(n)
    p_gil.append(m2)

    # ── SCENE 12 — Judgment of Gods (T14 Shamhat a cappella) ─────────
    sc12_offset = act4_offset + 10

    ts12 = meter.TimeSignature('4/4')

    m = stream.Measure(number=sc12_offset)
    m.append(key.Key('a', 'minor'))
    m.append(ts12)
    m.append(MetronomeMark(number=55, text="Libero — Suд bogov"))
    add_rehearsal(m, "Sc.12: Sud bogov — T14 Proklyatiye Shamhat")
    add_text(m, "Pustaya stsena. Golosa bogov nevidimi. Shamhat — posledniy raz.")
    m.append(R(4.0))
    p_sha.append(m)

    T14_pitches = ['A4','G4','F4','E4','D4','C4','D4','E4','F4','G4','A4',
                   'G4','A4','B4','C5','B4','A4','G4','F4','E4','D4',
                   'A5','G5','F5','E5','D5','C5','B4','A4']
    T14_lyr = ['da-','tsq-','ev-','li-','li','iq-','os','es','dge!','me','mov-',
               'ka-','li','is','che-','mi','siq-','va-','ru-','lith!',
               None,None,None,None,None,None,None,None]
    T14_dyn = {0:'p', 8:'mf', 14:'ff', 20:'p'}

    for i in range(0, len(T14_pitches), 4):
        chunk = T14_pitches[i:i+4]
        ll    = T14_lyr[i:i+4]
        m2 = stream.Measure(number=sc12_offset+1+i//4)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 1.0)
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            abs_idx = i + j
            if abs_idx in T14_dyn:
                n.expressions.append(dynamics.Dynamic(T14_dyn[abs_idx]))
            m2.append(n)
        p_sha.append(m2)

    # Enkidu acceptance
    m = stream.Measure(number=sc12_offset + 8)
    m.append(key.Key('a', 'minor'))
    m.append(ts12)
    add_text(m, "Enkidu prinimayet prigovor s dostoinstvom: 'Kargi. Me vitsi.'")
    m.append(R(4.0))
    p_enc.append(m)
    for p_str, lyr_w, dur in [
        ('A4','Kar-',2.0),('G4','gi.',2.0),
        ('E4','Me',2.0),('D4','vit-si.',2.0),
    ]:
        if not hasattr(p_enc, '_enc_acc'):
            m2 = stream.Measure(number=sc12_offset+9)
            p_enc._enc_acc = m2
            p_enc.append(m2)
        n = N(p_str, dur)
        n.addLyric(lyr_w)
        n.expressions.append(dynamics.Dynamic('pp'))
        p_enc._enc_acc.append(n)

    # ── SCENE 13 — Death of Enkidu (T6+T10+T2) ───────────────────────
    sc13_offset = sc12_offset + 12

    ks13 = key.Key('d', 'minor')
    ts13 = meter.TimeSignature('4/4')
    mm13 = MetronomeMark(number=40, text="Lento molto rubato — T6 Virishkhau")

    m = stream.Measure(number=sc13_offset)
    m.append(ks13)
    m.append(ts13)
    m.append(mm13)
    add_rehearsal(m, "Sc.13: Smert Enkidu — SAMAYA TIKHAYA STSENA")
    add_text(m, "Nochi. Enkidu na lozhe. Gilgamesh — sprava, Ninsun — sleva. Trio — v raznykh uglakh.")
    m.append(R(4.0))
    p_enc.append(m)

    # T6 Virishkhau — Enkidu's final song
    T6_enc = ['A4','G4','E4','D4','C4','A3']
    T6_lyr = ['vi-','rish-','kha-','u...','tq-','e...']
    for i in range(0, len(T6_enc), 2):
        m2 = stream.Measure(number=sc13_offset+1+i//2)
        for j in range(2):
            if i+j < len(T6_enc):
                n = N(T6_enc[i+j], 2.0)
                n.addLyric(T6_lyr[i+j])
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic('p'))
                m2.append(n)
        p_enc.append(m2)

    # Lamuri last — D4 pppp → 0
    m = stream.Measure(number=sc13_offset)
    m.append(ks13)
    m.append(ts13)
    add_text(m, "LAMURI: D4 pppp — echo (posedny raz v opere do Akta V)")
    m.append(R(4.0))
    p_lam.append(m)
    m2 = stream.Measure(number=sc13_offset+1)
    n_lam = N('D4', 4.0)
    n_lam.expressions.append(dynamics.Dynamic('pppp'))
    m2.append(n_lam)
    p_lam.append(m2)
    m3 = stream.Measure(number=sc13_offset+2)
    m3.append(R(4.0))
    p_lam.append(m3)

    # Ninsun T10 — lament for Enkidu
    mm13n = MetronomeMark(number=46, text="Lento doloroso — T10 Samkurao (Ninsun plachet)")
    T10_n = ['D4','F4','E4','D4','C4','D4','F4','G4','A4','G4','F4','E4','D4']
    T10_nl = ['sam-','ku-','ra-','o,','sam-','ku-','ra-','o,','chqi-','mi','chqvi-','de,','sam-']

    m = stream.Measure(number=sc13_offset + 4)
    m.append(ks13)
    m.append(ts13)
    m.append(mm13n)
    add_text(m, "Ninsun plachet za Gilgamesha (on ne mozhet plakat)")
    m.append(R(4.0))
    p_nin.append(m)

    for i in range(0, len(T10_n), 4):
        chunk = T10_n[i:i+4]
        ll    = T10_nl[i:i+4]
        m2 = stream.Measure(number=sc13_offset+5+i//4)
        for j, p_str in enumerate(chunk):
            n = N(p_str, 1.0)
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('p'))
            m2.append(n)
        p_nin.append(m2)

    # Trio T2 — FIRST TIME DISSONANT (falls apart)
    mm13t2 = MetronomeMark(number=88, text="Agitato — T2: TRIO PERVIY RAZ V RAZLADE!!!")
    T2_mk = ['C#5','G5','A5','F5','B5','D#5','G#5','E5','F5']
    T2_mt = ['A4','G#4','G4','F#4','F4','E4','D#4','D4','C#4']
    T2_ba = ['D3','D3','E-3','D3']

    for p_t, pts_t2, dyn_t2, clef_obj in [
        (p_mk, T2_mk, 'f', None),
        (p_mt, T2_mt, 'f', None),
        (p_ba, T2_ba, 'mf', clef.BassClef()),
    ]:
        m = stream.Measure(number=sc13_offset + 8)
        m.append(ts13)
        m.append(mm13t2)
        add_text(m, "T2 — Trio v razlade. Trio v raznykh uglakh stseny.")
        if clef_obj:
            m.append(clef_obj)
        p_t.append(m)
        for i in range(0, len(pts_t2), 4):
            chunk = pts_t2[i:i+4]
            m2 = stream.Measure(number=sc13_offset+9+i//4)
            for j, p_str in enumerate(chunk):
                n = N(p_str, 1.0)
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(dyn_t2))
                m2.append(n)
            p_t.append(m2)

    # ════════════════════════════════════════════════════════════════════
    # ACT V — "SEARCH FOR IMMORTALITY"
    # ════════════════════════════════════════════════════════════════════

    act5_offset = sc13_offset + 16

    # ── SCENE 14 — Gilgamesh's Lament (T2 full atonal) ───────────────
    ts14 = meter.TimeSignature('4/4')
    mm14 = MetronomeMark(number=88, text="Agitato — T2 polniy razlad Trio")

    m = stream.Measure(number=act5_offset)
    m.append(ts14)
    m.append(mm14)
    add_rehearsal(m, "ACT V · Sc.14: Plach Gilgamesha (T2 fff)")
    add_text(m, "Step. Odinochestvo. Trio — 3 ugla stseny. Gilgamesh obvinyayet Trio.")
    m.append(R(4.0))
    p_gil.append(m)

    # Gilgamesh aria — accusation
    gil_acc = ['A3','C4','D4','F4','E4','D4','A4','G4','F4','E4']
    gil_lyr = ['Vin','khar-','th?!','Vin','khar-','th,','sa-','mi','chve-','ni?!']
    for i in range(0, len(gil_acc), 4):
        m2 = stream.Measure(number=act5_offset+1+i//4)
        for j, p_str in enumerate(gil_acc[i:i+4]):
            n = N(p_str, 1.0)
            ll_idx = i + j
            if ll_idx < len(gil_lyr):
                n.addLyric(gil_lyr[ll_idx])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('fff'))
            m2.append(n)
        p_gil.append(m2)

    # T2 full — Trio in three separate keys simultaneously
    T2_mk2 = ['C#5','G5','A5','F5','B5','D#5','G#5','E5']
    T2_mt2 = ['A4','G#4','G4','F#4','F4','E4','D#4','D4']
    T2_ba2 = ['D3','C#3','D3','E-3','D3','C#3','D3','C3']

    for p_t, pts, dyn_v, c_obj in [
        (p_mk, T2_mk2, 'fff', None),
        (p_mt, T2_mt2, 'fff', None),
        (p_ba, T2_ba2, 'ff',  clef.BassClef()),
    ]:
        m = stream.Measure(number=act5_offset)
        m.append(ts14)
        add_text(m, "T2 fff — Trio razvalivayetsya")
        if c_obj: m.append(c_obj)
        p_t.append(m)
        for i in range(0, len(pts), 4):
            m2 = stream.Measure(number=act5_offset+1+i//4)
            for j, p_str in enumerate(pts[i:i+4]):
                n = N(p_str, 1.0)
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(dyn_v))
                m2.append(n)
            p_t.append(m2)

    # ── SCENE 15 — Scorpions / Waters of Death ────────────────────────
    sc15_offset = act5_offset + 8

    mm15 = MetronomeMark(number=40, text="Lento — E pedal (smert nezmenima)")
    m = stream.Measure(number=sc15_offset)
    m.append(key.Key('e', 'minor'))
    m.append(ts14)
    m.append(mm15)
    add_rehearsal(m, "Sc.15: Vody smerti — E pedal violoncheli")
    add_text(m, "Kraj mira. Gory Mashu. Minimalizm. Percussivnye ostinato.")
    # E pedal in piano
    for rep in range(6):
        m2 = stream.Measure(number=sc15_offset+rep)
        n_ped = N('E2', 4.0)
        if rep == 0:
            n_ped.expressions.append(dynamics.Dynamic('pppp'))
        m2.append(n_ped)
        p_pno.append(m2)

    # Shadows chorus pp
    m = stream.Measure(number=sc15_offset)
    m.append(key.Key('e', 'minor'))
    m.append(ts14)
    add_text(m, "Khor teney (za stseny) pp: 'Vin ikhe?'")
    m.append(R(4.0))
    p_chor.append(m)
    shadow_pts = ['E3','G3','A3','B3','A3','G3','E3','D3']
    shadow_lyr = ['Vin','i-','khe?','Vin','i-','khe?','Vin','mo-']
    for i in range(0, len(shadow_pts), 4):
        m2 = stream.Measure(number=sc15_offset+1+i//4)
        for j, p_str in enumerate(shadow_pts[i:i+4]):
            n = N(p_str, 1.0)
            n.addLyric(shadow_lyr[i+j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('pp'))
            m2.append(n)
        p_chor.append(m2)

    # ── SCENE 16 — Utnapishtim ────────────────────────────────────────
    sc16_offset = sc15_offset + 8

    ks16 = key.Key('G')
    ts16 = meter.TimeSignature('4/4')
    mm16 = MetronomeMark(number=66, text="Andante — Utnapishtim (vne stilya)")

    m = stream.Measure(number=sc16_offset)
    m.append(ks16)
    m.append(ts16)
    m.append(mm16)
    add_rehearsal(m, "Sc.16: Utnapishtim — G major (prinyatiye)")
    add_text(m, "Ostrov. Zolotoy rassvet. Utnapishtim sidit — nepodvizhen. Trio sblizhayutsya.")
    m.append(R(4.0))
    p_utn.append(m)

    # Utnapishtim sings — neutral (no regional style)
    utn_pts = ['G4','B4','D5','B4','G4','A4','B4','D5','B4','A4','G4','F#4','G4']
    utn_lyr = ['Gil-','ga-','mesh...','me','mik-','virs','shen.','K-','var-','ti.','E-','mu','vitsi.']
    for i in range(0, len(utn_pts), 4):
        m2 = stream.Measure(number=sc16_offset+1+i//4)
        for j, p_str in enumerate(utn_pts[i:i+4]):
            n = N(p_str, 1.0)
            ll_idx = i + j
            if ll_idx < len(utn_lyr):
                n.addLyric(utn_lyr[ll_idx])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('p'))
            m2.append(n)
        p_utn.append(m2)

    # Gilgamesh finds flower — brief ff
    m = stream.Measure(number=sc16_offset + 5)
    m.append(ks16)
    m.append(ts16)
    add_text(m, "Tsvetok nayden → zmea unosit → tishina → prinyatiye")
    m.append(R(4.0))
    p_gil.append(m)
    flower_pts = ['G4','B4','D5','G5','D5','B4','G4']
    flower_lyr = ['I-','po-','va!','I-','po-','va!','!']
    m2 = stream.Measure(number=sc16_offset+6)
    for p_str, lyr_w in zip(flower_pts[:4], flower_lyr[:4]):
        n = N(p_str, 1.0)
        n.addLyric(lyr_w)
        n.expressions.append(dynamics.Dynamic('ff'))
        m2.append(n)
    p_gil.append(m2)
    m3 = stream.Measure(number=sc16_offset+7)
    m3.append(R(4.0))
    add_text(m3, "TISHINA — zmea unosit tsvetok")
    p_gil.append(m3)

    # Gilgamesh acceptance
    m4 = stream.Measure(number=sc16_offset+8)
    for p_str, lyr_w, dur in [('G4','Tsa-',2.0),('E4','ri.',2.0)]:
        n = N(p_str, dur)
        n.addLyric(lyr_w)
        n.expressions.append(dynamics.Dynamic('pp'))
        m4.append(n)
    p_gil.append(m4)
    m5 = stream.Measure(number=sc16_offset+9)
    for p_str, lyr_w, dur in [('D4','Kar-',2.0),('G4','gi.',2.0)]:
        n = N(p_str, dur)
        n.addLyric(lyr_w)
        m5.append(n)
    p_gil.append(m5)

    # Trio T3 pp — tentative beginning
    for p_t, pts_t3, d_t3, c_obj in [
        (p_mk, ['D5','F#5','A5','G5','F#5','E5','D5'], 'pp', None),
        (p_mt, ['A4','D5','F#5','E5','D5','C#5','D4'], 'pp', None),
        (p_ba, ['D3','A3','D4','A3','D3','A2','D3'],   'pp', clef.BassClef()),
    ]:
        m = stream.Measure(number=sc16_offset + 8)
        m.append(ks16)
        m.append(ts16)
        m.append(MetronomeMark(number=66, text="T3 pp — Trio robko nakhodit garmoniu"))
        add_text(m, "T3 Alilo pp — nachinaetsya (robko, perviy raz s IV akta)")
        if c_obj: m.append(c_obj)
        p_t.append(m)
        for i in range(0, len(pts_t3), 4):
            m2 = stream.Measure(number=sc16_offset+9+i//4)
            for j, p_str in enumerate(pts_t3[i:i+4]):
                n = N(p_str, 1.0)
                n.addLyric('a-' if j % 2 == 0 else 'li-')
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(d_t3))
                m2.append(n)
            p_t.append(m2)

    # ── SCENE 17 — FINALE — Walls of Uruk ────────────────────────────
    sc17_offset = sc16_offset + 14

    ks17 = key.Key('D')
    ts17 = meter.TimeSignature('4/4')
    mm17_fin = MetronomeMark(number=66, text="Andante tranquillo → Allegro moderato — FINALE")

    # T3 Alilo — Trio FULL HARMONY (first since Act II)
    T3_mk = ['D5','F#5','A5','G5','F#5','E5','D5','C#5','D5','A4','D5']
    T3_mt = ['A4','D5','F#5','E5','D5','C#5','D4','B3','A4','F#4','A4']
    T3_ba = ['D3','A3','D4','A3','D3','A2','D3','A2','D3','D2','D3']
    T3_lyr_t = ['a-','li-','lo,','a-','li-','lo,','a-','li-','lo,','a-','li-']

    m = stream.Measure(number=sc17_offset)
    m.append(ks17)
    m.append(ts17)
    m.append(mm17_fin)
    add_rehearsal(m, "ACT V · Sc.17: FINALE — Steny Uruka (T3 Alilo + T11 Lile)")
    add_text(m, "Uruk. Rassvet. Gilgamesh smotrit na steny. PERVIY RAZ s Akta II — Trio v POLNOY garmonii.")
    m.append(R(4.0))
    p_mk.append(m)

    for p_t, pts, d_t, c_obj in [
        (p_mk, T3_mk, 'p',  None),
        (p_mt, T3_mt, 'p',  None),
        (p_ba, T3_ba, 'p',  clef.BassClef()),
    ]:
        for i in range(0, len(pts), 4):
            chunk = pts[i:i+4]
            ll    = T3_lyr_t[i:i+4]
            m2 = stream.Measure(number=sc17_offset+1+i//4)
            for j, p_str in enumerate(chunk):
                n = N(p_str, 1.0)
                if j < len(ll) and ll[j]:
                    n.addLyric(ll[j])
                if i == 0 and j == 0:
                    n.expressions.append(dynamics.Dynamic(d_t))
                m2.append(n)
            p_t.append(m2)

    # T11 Lile — Ninsun + women's choir (D major, fast)
    mm11_lile = MetronomeMark(number=96, text="Allegro moderato — T11 Lile")
    T11_s1 = ['D5','F5','E5','D5','C5','D5','F5','G5','A5','G5','F5','E5','D5']
    T11_s2 = ['A4','C5','B4','A4','G4','A4','C5','D5','E5','D5','C5','B4','A4']
    T11_al = ['D4','F4','E4','D4','C4','D4','F4','G4','A4','G4','F4','E4','D4']
    T11_lyr = ['li-','le,','li-','le,','o-','ro-','ve-','la,','si-','tso-','tskhle','grdze-','ldeba!']

    m = stream.Measure(number=sc17_offset + 4)
    m.append(ks17)
    m.append(ts17)
    m.append(mm11_lile)
    add_text(m, "T11 Lile — Ninsun + zhensky khor SSA ff")
    m.append(R(4.0))
    p_nin.append(m)

    for i in range(0, len(T11_s1), 4):
        chunk_s1 = T11_s1[i:i+4]
        ll = T11_lyr[i:i+4]
        m2 = stream.Measure(number=sc17_offset+5+i//4)
        for j, p_str in enumerate(chunk_s1):
            n = N(p_str, 1.0)
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('mf'))
            m2.append(n)
        p_nin.append(m2)

    # Choir T11 (Sop II + Alto combined for choir part)
    m = stream.Measure(number=sc17_offset + 4)
    m.append(ks17)
    m.append(ts17)
    m.append(R(4.0))
    p_chor.append(m)
    for i in range(0, len(T11_al), 4):
        chunk_al = T11_al[i:i+4]
        ll = T11_lyr[i:i+4]
        m2 = stream.Measure(number=sc17_offset+5+i//4)
        for j, p_str in enumerate(chunk_al):
            n = N(p_str, 1.0)
            if j < len(ll) and ll[j]:
                n.addLyric(ll[j])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('mf'))
            m2.append(n)
        p_chor.append(m2)

    # Svan echo — offstage pppp (Virishkhau memory)
    m = stream.Measure(number=sc17_offset + 8)
    m.append(ks17)
    m.append(ts17)
    add_text(m, "Svanskiy kvartet (za stseny) pppp — pamyat ob Enkidu: 'Vi-rish-khau...'")
    m.append(R(4.0))
    p_lam.append(m)
    svan_echo = ['D4','E4','G4','A4']
    svan_lyr  = ['Vi-','rish-','kha-','u...']
    m2 = stream.Measure(number=sc17_offset+9)
    for p_str, lyr_w in zip(svan_echo, svan_lyr):
        n = N(p_str, 1.0)
        n.addLyric(lyr_w)
        n.expressions.append(dynamics.Dynamic('pppp'))
        m2.append(n)
    p_lam.append(m2)

    # Gilgamesh SOLO — WITHOUT TRIO (first time ever)
    m = stream.Measure(number=sc17_offset + 6)
    m.append(ks17)
    m.append(ts17)
    add_text(m, "GILGAMESH SOLO BEZ TRIO — PERVIY RAZ V OPERE. On sam stal svoyey polifoniey.")
    m.append(R(4.0))
    p_gil.append(m)

    gil_solo = ['D4','F#4','A4','D5','A4','F#4','D4','E4','F#4','G4','A4','D5','D4']
    gil_solo_lyr = ['ai','ke-','dle-','bi.','ai','U-','ru-','qi.','ai','sis-','khli.','ai','sim-']
    for i in range(0, len(gil_solo), 4):
        m2 = stream.Measure(number=sc17_offset+7+i//4)
        for j, p_str in enumerate(gil_solo[i:i+4]):
            n = N(p_str, 1.0)
            ll_idx = i + j
            if ll_idx < len(gil_solo_lyr):
                n.addLyric(gil_solo_lyr[ll_idx])
            if i == 0 and j == 0:
                n.expressions.append(dynamics.Dynamic('p'))
            m2.append(n)
        p_gil.append(m2)

    # Final: "Me viyavi. Me var. Me viq'nebi."
    m_final_g = stream.Measure(number=sc17_offset + 12)
    last_words = [('D4','me',2.0),('F#4','vi-',1.0),('A4','ya-',1.0)]
    for p_str, lyr_w, dur in last_words:
        n = N(p_str, dur)
        n.addLyric(lyr_w)
        n.expressions.append(dynamics.Dynamic('p'))
        m_final_g.append(n)
    p_gil.append(m_final_g)

    m_f2 = stream.Measure(number=sc17_offset+13)
    for p_str, lyr_w, dur in [('G4','vi.',2.0),('A4','me',1.0),('D5','var.',1.0)]:
        n = N(p_str, dur)
        n.addLyric(lyr_w)
        m_f2.append(n)
    p_gil.append(m_f2)

    m_f3 = stream.Measure(number=sc17_offset+14)
    n_last = N('D4', 4.0)
    n_last.addLyric('me-viq-ne-bi.')
    n_last.expressions.append(dynamics.Dynamic('pp'))
    m_f3.append(n_last)
    p_gil.append(m_f3)

    # ── FINAL CELLO D PEDAL ───────────────────────────────────────────
    m = stream.Measure(number=sc17_offset + 10)
    m.append(ks17)
    m.append(ts17)
    m.append(MetronomeMark(number=40, text="Lento — D3 violonchel → pppp → 0"))
    add_text(m, "POSLEDNY ZVUK OPERY: D3 violonchel pppp → 0. On byl v nachale. On budet posle nas.")
    for rep in range(4):
        m2 = stream.Measure(number=sc17_offset+10+rep)
        n_ped = N('D2', 4.0)
        dyn_seq = ['pp','p','pp','pppp']
        n_ped.expressions.append(dynamics.Dynamic(dyn_seq[rep]))
        if rep == 3:
            m2.append(bar.Barline('final'))
        m2.append(n_ped)
        p_pno.append(m2)

    # ════════════════════════════════════════════════════════════════════
    # ASSEMBLE SCORE
    # ════════════════════════════════════════════════════════════════════

    for p_part in all_parts:
        if len(p_part) > 0:
            sc.append(p_part)

    return sc


# ─── MAIN ────────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    print("\n╔══════════════════════════════════════════════════════════╗")
    print("║  ŠAMNU AZUZI — MuseScore MusicXML Generator            ║")
    print("║  Полная партитура · 5 актов · 17 сцен · 20 тем         ║")
    print("╚══════════════════════════════════════════════════════════╝\n")

    print("Строю партитуру...")
    sc = build_score()

    print(f"Экспортирую в MusicXML → {OUT_FILE}")
    sc.write('musicxml', fp=OUT_FILE)

    print(f"\n✅  Готово: {OUT_FILE}")
    print(f"   Размер: {os.path.getsize(OUT_FILE) // 1024} KB")
    print("\nОткройте файл в MuseScore3:")
    print(f"   musescore3 '{OUT_FILE}'")
    print("\nСостав партитуры:")
    parts_names = [
        "Gilgamesh (Bar)","Enkidu (Ten)","Ninsun (MezzoSopr)",
        "Shamhat (Sopr)","Humbaba (Bass)","Utnapishtim (Bar)",
        "Mkrimani (Countertenor)","Mtavari (Ten)","Bani (Bass)",
        "Choir SATB","Lamuri (Flute)","Chuniri (Violin)",
        "Panduri (Guitar)","Piano (Reduction)"
    ]
    for n in parts_names:
        print(f"  • {n}")
