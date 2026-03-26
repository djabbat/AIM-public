#!/usr/bin/env python3
"""
ŠAMNU AZUZI — KRIMANCHULI TRIO
6 Georgian Folk Polyphonic Songs for Gilgamesh
Georgian krimanchuli style: Mkrimani + Mtavari + Bani (+ Gilgamesh in Songs 1 & 6)

Music and Libretto: Jaba Tkemaladze
Output: SAMNU_AZUZI_KrimanchuliTrio.musicxml
"""

import os
from music21 import (
    stream, note, chord, tempo, meter, key, dynamics,
    expressions, metadata, instrument, clef, bar, pitch,
    articulations, interval
)

OUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "SAMNU_AZUZI_KrimanchuliTrio.musicxml")

# ═══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ═══════════════════════════════════════════════════════════════

def make_note(p, dur):
    """Create a note or rest from pitch string and quarter-length duration."""
    if p == 'R':
        n = note.Rest(quarterLength=dur)
    else:
        n = note.Note(p, quarterLength=dur)
    return n


def make_measure(notes_list, ts_numerator=4, ts_denominator=4):
    """
    Build a single measure from a list of (pitch, duration) tuples.
    Does NOT attach a time signature — caller does that on first measure.
    """
    m = stream.Measure()
    beat_total = 0.0
    for (p, d) in notes_list:
        n = make_note(p, d)
        m.append(n)
        beat_total += d
    return m


def fill_measure_to(m, beats, fill_pitch='R'):
    """Append a rest to fill measure to 'beats' quarter-lengths."""
    used = sum(el.quarterLength for el in m.flatten().notesAndRests)
    remaining = beats - used
    if remaining > 0.001:
        m.append(make_note(fill_pitch, remaining))


def make_grace(pitch_str):
    """Create a grace note with GraceDuration."""
    gn = note.Note(pitch_str)
    gn.duration = gn.duration.getGraceDuration()
    return gn


def add_grace_before(m, grace_pitch, main_pitch_obj):
    """
    Insert a grace note (acciaccatura) before the first occurrence
    of a specific note object in measure m.
    """
    gn = make_grace(grace_pitch)
    idx = m.index(main_pitch_obj)
    m.insert(main_pitch_obj.offset - 0.001, gn)


def build_part(name, instr_obj, clef_obj):
    """Initialize a Part with instrument and clef."""
    p = stream.Part()
    p.id = name
    p.insert(0, instr_obj)
    p.insert(0, clef_obj)
    return p


def add_rehearsal(part, offset, text):
    """Add a rehearsal mark at given offset."""
    rm = expressions.RehearsalMark(text)
    rm.style.fontSize = 14
    part.insert(offset, rm)


def repeat_pattern(pattern, n_measures, beats_per_measure):
    """
    Repeat a note pattern to fill n_measures.
    Pattern is list of (pitch, dur) tuples — will loop and trim.
    Returns list of (pitch, dur) lists, one per measure.
    """
    all_notes = []
    while len(all_notes) < n_measures * beats_per_measure * 4:  # safety overrun
        all_notes.extend(pattern)
        if len(all_notes) > n_measures * 200:
            break

    measures = []
    remaining = list(all_notes)
    for _ in range(n_measures):
        bucket = []
        total = 0.0
        while remaining and total < beats_per_measure - 0.001:
            p, d = remaining[0]
            if total + d <= beats_per_measure + 0.001:
                bucket.append((p, d))
                total += d
                remaining.pop(0)
            else:
                # split the note
                take = beats_per_measure - total
                bucket.append((p, take))
                remaining[0] = (p, d - take)
                total = beats_per_measure
        measures.append(bucket)
    return measures


# ═══════════════════════════════════════════════════════════════
# SONG THEMES — exact as specified
# ═══════════════════════════════════════════════════════════════

# ---- Song 1: Mravalzhamier (D Dorian, 4/4) ----
S1_mkrimani = [('G4',1),('B4',0.5),('D5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',1),('C5',0.5),('B4',0.5),('A4',0.5),('G4',1.5)]
S1_mtavari  = [('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',0.5),
               ('G4',0.5),('F4',1),('E4',0.5),('D4',1.5)]
S1_bani_start = [('D2',2),('D3',2)]
S1_bani_cadence = [('A2',2),('A2',2)]

# ---- Song 2: Khasanbegura (G minor, 6/8, dotted-quarter=80) ----
S2_mkrimani = [('D4',0.75),('F#4',0.5),('A4',0.75),('D5',0.5),('C5',0.5),
               ('B4',0.75),('A4',0.5),('G4',0.5),('F#4',0.75),('E4',0.5),('D4',1)]
S2_mtavari  = [('G4',1.5),('F4',0.75),('Eb4',0.75),('D4',1.5),('G3',1.5)]
S2_bani_pat = [('G2',1.5),('G2',1.5)]   # 6/8 = 1.5 quarter-lengths per beat

# ---- Song 3: Tsintskaro (D major, 5/8) ----
S3_mkrimani = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',1),('C#5',0.5),('D5',1.5)]
S3_mtavari  = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),
               ('C#5',0.5),('D4',1),('B3',0.5),('A4',1.5)]

# ---- Song 4: Beri Berikaoba (G minor, 3/4) ----
S4_mkrimani = [('G4',0.75),('B4',0.5),('D5',0.75),('C5',0.5),('B4',0.5),
               ('A4',0.75),('G4',0.5),('F#4',0.5),('G4',1)]
S4_mtavari  = [('D4',1),('F4',0.5),('Eb4',0.5),('D4',1),('C4',0.5),
               ('Bb3',0.5),('D4',1.5)]
S4_bani_pat = [('G2',1),('G2',1),('D2',1)]

# ---- Song 5: Mze Shina (D minor→Bb→unresolved, 4/4) ----
S5_mkrimani_harm = [('A4',1),('C5',1),('B4',0.5),('A4',0.5),('G4',1),('F4',0.5),
                    ('E4',0.5),('D4',1),('F4',0.5),('A4',0.5),('C5',1),('B4',0.5),
                    ('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',2)]
# Dissonant variant — flatten key notes
S5_mkrimani_dis  = [('A4',1),('C5',1),('Bb4',0.5),('Ab4',0.5),('G4',1),('F4',0.5),
                    ('Eb4',0.5),('D4',1),('F4',0.5),('Ab4',0.5),('C5',1),('Bb4',0.5),
                    ('Ab4',0.5),('G4',1),('F4',0.5),('Eb4',0.5),('D4',2)]
# Mtavari = same contour a third lower
S5_mtavari_harm  = [('F4',1),('Ab4',1),('G4',0.5),('F4',0.5),('Eb4',1),('D4',0.5),
                    ('C4',0.5),('Bb3',1),('D4',0.5),('F4',0.5),('Ab4',1),('G4',0.5),
                    ('F4',0.5),('Eb4',1),('D4',0.5),('C4',0.5),('Bb3',2)]
S5_mtavari_dis   = [('F4',1),('Ab4',1),('Gb4',0.5),('F4',0.5),('Eb4',1),('Db4',0.5),
                    ('C4',0.5),('Bb3',1),('Db4',0.5),('F4',0.5),('Ab4',1),('Gb4',0.5),
                    ('F4',0.5),('Eb4',1),('Db4',0.5),('C4',0.5),('Bb3',2)]

# ---- Song 6: Alilo (D major→D Mixolydian, 4/4) ----
S6_mkrimani = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),
               ('E5',0.5),('D5',0.5),('C#5',0.5),('D5',0.5),('A4',0.5),('D5',1)]
S6_mtavari  = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),
               ('C#5',0.5),('D4',0.5),('B3',0.5),('A4',0.5),('F#4',0.5),('A4',1)]
S6_bani     = [('D3',1),('A3',0.5),('D4',0.5),('A3',1),('D3',0.5),
               ('A2',0.5),('D3',0.5),('A2',0.5),('D3',0.5),('D2',0.5),('D3',1)]
# Gilgamesh in finale — T3_mtavari an octave lower
S6_gilga    = [('A3',1),('D4',0.5),('F#4',0.5),('E4',1),('D4',0.5),
               ('C#4',0.5),('D3',0.5),('B2',0.5),('A3',0.5),('F#3',0.5),('A3',1)]


# ═══════════════════════════════════════════════════════════════
# MEASURE BUILDERS
# ═══════════════════════════════════════════════════════════════

def build_measures_from_pattern(pattern, n_measures, beats):
    """Loop pattern across n_measures of 'beats' quarter-length each."""
    mlist = repeat_pattern(pattern, n_measures, beats)
    result = []
    for notes_data in mlist:
        m = stream.Measure()
        for (p, d) in notes_data:
            m.append(make_note(p, d))
        result.append(m)
    return result


def bani_drone(pitch_str, dur, beats, n_measures):
    """Build drone measures — half notes or whole notes only."""
    measures = []
    for i in range(n_measures):
        m = stream.Measure()
        remaining = beats
        while remaining > 0.001:
            step = min(dur, remaining)
            m.append(make_note(pitch_str, step))
            remaining -= step
        measures.append(m)
    return measures


def bani_octave_drone(p1, p2, beats, n_measures):
    """Alternate between two pitches in half-note values."""
    measures = []
    for i in range(n_measures):
        m = stream.Measure()
        m.append(make_note(p1, beats / 2))
        m.append(make_note(p2, beats / 2))
        measures.append(m)
    return measures


# ═══════════════════════════════════════════════════════════════
# SCORE ASSEMBLY
# ═══════════════════════════════════════════════════════════════

def build_score():
    sc = stream.Score()

    # Metadata
    md = metadata.Metadata()
    md.title = "Šamnu Azuzi — Krimanchuli Trio"
    md.composer = "Jaba Tkemaladze"
    sc.metadata = md

    # ── Four parts ──────────────────────────────────────────────
    part_mkrimani  = stream.Part()
    part_mkrimani.id  = 'Mkrimani'
    part_mkrimani.partName = 'Mkrimani (მკრიმანი)'

    part_mtavari   = stream.Part()
    part_mtavari.id   = 'Mtavari'
    part_mtavari.partName = 'Mtavari (მთავარი)'

    part_bani      = stream.Part()
    part_bani.id      = 'Bani'
    part_bani.partName = 'Bani (ბანი)'

    part_gilgamesh = stream.Part()
    part_gilgamesh.id = 'Gilgamesh'
    part_gilgamesh.partName = 'Gilgamesh (ბარიტონი)'

    # Instruments & clefs (inserted at measure 1 start)
    instr_mk = instrument.Soprano()
    instr_mk.instrumentName = 'Mkrimani'
    instr_mk.instrumentAbbreviation = 'Mk.'

    instr_mt = instrument.Tenor()
    instr_mt.instrumentName = 'Mtavari'
    instr_mt.instrumentAbbreviation = 'Mt.'

    instr_ba = instrument.Bass()
    instr_ba.instrumentName = 'Bani'
    instr_ba.instrumentAbbreviation = 'Ba.'

    instr_gi = instrument.Baritone()
    instr_gi.instrumentName = 'Gilgamesh'
    instr_gi.instrumentAbbreviation = 'Gi.'

    # ════════════════════════════════════════════════════════════
    # SONG 1: Mravalzhamier — 32 measures, 4/4, D Dorian, ♩=60
    # ════════════════════════════════════════════════════════════
    beats1 = 4.0
    n1 = 32

    mk1_measures = build_measures_from_pattern(S1_mkrimani, n1, beats1)
    mt1_measures = build_measures_from_pattern(S1_mtavari,  n1, beats1)

    # Bani: D2-D3 octave drone, shifts to A2 every 4th measure (cadence)
    ba1_measures = []
    for i in range(n1):
        m = stream.Measure()
        if (i + 1) % 4 == 0:
            # cadence: A2 whole note
            m.append(make_note('A2', 2))
            m.append(make_note('A2', 2))
        else:
            m.append(make_note('D2', 2))
            m.append(make_note('D3', 2))
        ba1_measures.append(m)

    # Gilgamesh (joins Song 1): T3_mtavari an octave lower pattern
    gi1_measures = build_measures_from_pattern(
        [(p.replace('4','3').replace('5','4').replace('3','2') if p != 'R' else 'R', d)
         for (p, d) in S6_gilga], n1, beats1)

    # Add rehearsal mark and time sig to first measure of each part
    def init_song1_measure(m, is_first, ts, ks, mm_tempo=None, rm_text=None, instr=None, cl=None):
        if is_first:
            if instr:  m.insert(0, instr)
            if cl:     m.insert(0, cl)
            if rm_text:
                rm = expressions.RehearsalMark(rm_text)
                rm.style.fontSize = 12
                m.insert(0, rm)
            m.insert(0, ts)
            m.insert(0, ks)
            if mm_tempo:
                m.insert(0, mm_tempo)

    ts1 = meter.TimeSignature('4/4')
    ks1 = key.Key('D', 'dorian')   # D Dorian
    mm1 = tempo.MetronomeMark(number=60, referent=note.Note(type='quarter'))

    for i, (mk_m, mt_m, ba_m, gi_m) in enumerate(
            zip(mk1_measures, mt1_measures, ba1_measures, gi1_measures)):
        is_f = (i == 0)
        if is_f:
            rm = expressions.RehearsalMark("Song 1: Mravalzhamier (მრავალჟამიერ)")
            rm.style.fontSize = 11
            mk_m.insert(0, rm)
            mk_m.insert(0, meter.TimeSignature('4/4'))
            mk_m.insert(0, key.Key('d'))
            mk_m.insert(0, tempo.MetronomeMark(number=60,
                         referent=note.Note(type='quarter')))
            mk_m.insert(0, instr_mk)
            mk_m.insert(0, clef.TrebleClef())

            mt_m.insert(0, meter.TimeSignature('4/4'))
            mt_m.insert(0, key.Key('d'))
            mt_m.insert(0, tempo.MetronomeMark(number=60,
                         referent=note.Note(type='quarter')))
            mt_m.insert(0, instr_mt)
            mt_m.insert(0, clef.TrebleClef())

            ba_m.insert(0, meter.TimeSignature('4/4'))
            ba_m.insert(0, key.Key('d'))
            ba_m.insert(0, tempo.MetronomeMark(number=60,
                         referent=note.Note(type='quarter')))
            ba_m.insert(0, instr_ba)
            ba_m.insert(0, clef.BassClef())

            gi_m.insert(0, meter.TimeSignature('4/4'))
            gi_m.insert(0, key.Key('d'))
            gi_m.insert(0, tempo.MetronomeMark(number=60,
                         referent=note.Note(type='quarter')))
            gi_m.insert(0, instr_gi)
            gi_m.insert(0, clef.BassClef())

        # Grace note ornament on Mkrimani beat 1 (every other measure)
        if i % 2 == 0:
            mk_notes = [n for n in mk_m.notes]
            if mk_notes:
                gn = make_grace('A4')
                mk_m.insertAndShift(mk_notes[0].offset, gn)

        part_mkrimani.append(mk_m)
        part_mtavari.append(mt_m)
        part_bani.append(ba_m)
        part_gilgamesh.append(gi_m)

    # ════════════════════════════════════════════════════════════
    # SONG 2: Khasanbegura — 32 measures, 6/8, G minor, ♩.=80
    # ════════════════════════════════════════════════════════════
    beats2 = 3.0   # 6/8 = 3 quarter-length beats
    n2 = 32

    mk2_measures = build_measures_from_pattern(S2_mkrimani, n2, beats2)
    mt2_measures = build_measures_from_pattern(S2_mtavari,  n2, beats2)

    ba2_measures = []
    for i in range(n2):
        m = stream.Measure()
        # boom-chk: dotted quarter + eighth = 1.5 + 0.5 = 2.0 ql
        # two groups per 6/8 bar
        if (i + 1) % 4 == 0:
            m.append(make_note('D2', 1.5))
            m.append(make_note('D2', 0.5))
            m.append(make_note('D3', 1.0))
        else:
            m.append(make_note('G2', 1.5))
            m.append(make_note('G2', 0.5))
            m.append(make_note('G3', 1.0))
        ba2_measures.append(m)

    # Gilgamesh: rests in Song 2 (does not join)
    gi2_measures = []
    for i in range(n2):
        m = stream.Measure()
        m.append(note.Rest(quarterLength=beats2))
        gi2_measures.append(m)

    for i, (mk_m, mt_m, ba_m, gi_m) in enumerate(
            zip(mk2_measures, mt2_measures, ba2_measures, gi2_measures)):
        is_f = (i == 0)
        if is_f:
            rm = expressions.RehearsalMark("Song 2: Khasanbegura (ხასანბეგურა)")
            rm.style.fontSize = 11
            mk_m.insert(0, rm)
            mk_m.insert(0, meter.TimeSignature('6/8'))
            mk_m.insert(0, key.Key('g'))
            from music21 import duration as dur_mod
            _d = dur_mod.Duration('quarter')
            _d.dots = 1
            mm2 = tempo.MetronomeMark(number=80, referent=_d)
            mk_m.insert(0, mm2)

            mt_m.insert(0, meter.TimeSignature('6/8'))
            mt_m.insert(0, key.Key('g'))
            ba_m.insert(0, meter.TimeSignature('6/8'))
            ba_m.insert(0, key.Key('g'))
            gi_m.insert(0, meter.TimeSignature('6/8'))
            gi_m.insert(0, key.Key('g'))

        # Aggressive eighth runs on Mkrimani (mark staccato on first note)
        mk_notes = [n for n in mk_m.notes]
        if mk_notes:
            mk_notes[0].articulations.append(articulations.Accent())

        part_mkrimani.append(mk_m)
        part_mtavari.append(mt_m)
        part_bani.append(ba_m)
        part_gilgamesh.append(gi_m)

    # ════════════════════════════════════════════════════════════
    # SONG 3: Tsintskaro — 32 measures, 5/8, D major, ♩=66
    # Bani is SILENT (drama: no shadow in dreams)
    # ════════════════════════════════════════════════════════════
    beats3 = 2.5   # 5/8 in quarter-lengths
    n3 = 32

    mk3_measures = build_measures_from_pattern(S3_mkrimani, n3, beats3)
    mt3_measures = build_measures_from_pattern(S3_mtavari,  n3, beats3)

    # Bani and Gilgamesh: full rests
    ba3_measures = []
    gi3_measures = []
    for i in range(n3):
        mb = stream.Measure()
        mb.append(note.Rest(quarterLength=beats3))
        ba3_measures.append(mb)
        mg = stream.Measure()
        mg.append(note.Rest(quarterLength=beats3))
        gi3_measures.append(mg)

    for i, (mk_m, mt_m, ba_m, gi_m) in enumerate(
            zip(mk3_measures, mt3_measures, ba3_measures, gi3_measures)):
        is_f = (i == 0)
        if is_f:
            rm = expressions.RehearsalMark("Song 3: Tsintskaro (წინწყარო)")
            rm.style.fontSize = 11
            mk_m.insert(0, rm)
            mk_m.insert(0, meter.TimeSignature('5/8'))
            mk_m.insert(0, key.Key('D'))
            mk_m.insert(0, tempo.MetronomeMark(number=66,
                         referent=note.Note(type='quarter')))

            mt_m.insert(0, meter.TimeSignature('5/8'))
            mt_m.insert(0, key.Key('D'))
            ba_m.insert(0, meter.TimeSignature('5/8'))
            ba_m.insert(0, key.Key('D'))
            gi_m.insert(0, meter.TimeSignature('5/8'))
            gi_m.insert(0, key.Key('D'))

        # Trill on Mkrimani F#5 and A5 notes
        for n_obj in mk_m.notes:
            if n_obj.pitch.name in ('F#', 'A') and n_obj.pitch.octave == 5:
                n_obj.expressions.append(expressions.Trill())

        part_mkrimani.append(mk_m)
        part_mtavari.append(mt_m)
        part_bani.append(ba_m)
        part_gilgamesh.append(gi_m)

    # ════════════════════════════════════════════════════════════
    # SONG 4: Beri Berikaoba — 32 measures, 3/4, G minor, ♩=76
    # ════════════════════════════════════════════════════════════
    beats4 = 3.0
    n4 = 32

    mk4_measures = build_measures_from_pattern(S4_mkrimani, n4, beats4)
    mt4_measures = build_measures_from_pattern(S4_mtavari,  n4, beats4)

    ba4_measures = []
    gi4_measures = []
    for i in range(n4):
        mb = stream.Measure()
        # March-like: G2 quarter + G2 quarter + D2 quarter
        if (i + 1) % 4 == 0:
            mb.append(make_note('D2', 1))
            mb.append(make_note('D2', 1))
            mb.append(make_note('G2', 1))
        else:
            mb.append(make_note('G2', 1))
            mb.append(make_note('G2', 1))
            mb.append(make_note('D2', 1))
        ba4_measures.append(mb)
        mg = stream.Measure()
        mg.append(note.Rest(quarterLength=beats4))
        gi4_measures.append(mg)

    for i, (mk_m, mt_m, ba_m, gi_m) in enumerate(
            zip(mk4_measures, mt4_measures, ba4_measures, gi4_measures)):
        is_f = (i == 0)
        if is_f:
            rm = expressions.RehearsalMark("Song 4: Beri Berikaoba (ბერი ბერიკაობა)")
            rm.style.fontSize = 11
            mk_m.insert(0, rm)
            mk_m.insert(0, meter.TimeSignature('3/4'))
            mk_m.insert(0, key.Key('g'))
            mk_m.insert(0, tempo.MetronomeMark(number=76,
                         referent=note.Note(type='quarter')))

            mt_m.insert(0, meter.TimeSignature('3/4'))
            mt_m.insert(0, key.Key('g'))
            ba_m.insert(0, meter.TimeSignature('3/4'))
            ba_m.insert(0, key.Key('g'))
            gi_m.insert(0, meter.TimeSignature('3/4'))
            gi_m.insert(0, key.Key('g'))

        # Staccato mock-serious on Mkrimani
        for n_obj in mk_m.notes:
            n_obj.articulations.append(articulations.Staccato())

        part_mkrimani.append(mk_m)
        part_mtavari.append(mt_m)
        part_bani.append(ba_m)
        part_gilgamesh.append(gi_m)

    # ════════════════════════════════════════════════════════════
    # SONG 5: Mze Shina — 40 measures, 4/4, D min→Bb→unresolved
    # m.1-16: harmonic; m.17-32: dissonant; m.33-40: unresolved
    # ════════════════════════════════════════════════════════════
    beats5 = 4.0
    n5 = 40

    # Build harmonic block (measures 1-16)
    mk5_harm = build_measures_from_pattern(S5_mkrimani_harm, 16, beats5)
    mt5_harm = build_measures_from_pattern(S5_mtavari_harm,  16, beats5)
    # Dissonant block (measures 17-32)
    mk5_dis  = build_measures_from_pattern(S5_mkrimani_dis,  16, beats5)
    mt5_dis  = build_measures_from_pattern(S5_mtavari_dis,   16, beats5)
    # Unresolved (measures 33-40) — further chromatic descent
    S5_mkrimani_unres = [('Ab4',1),('Bb4',1),('Ab4',0.5),('G4',0.5),
                         ('Gb4',1),('F4',0.5),('Eb4',0.5),('Db4',2)]
    S5_mtavari_unres  = [('Eb4',1),('F4',1),('Eb4',0.5),('Db4',0.5),
                         ('C4',1),('Bb3',0.5),('Ab3',0.5),('G3',2)]
    mk5_unres = build_measures_from_pattern(S5_mkrimani_unres, 8, beats5)
    mt5_unres = build_measures_from_pattern(S5_mtavari_unres,  8, beats5)

    mk5_all = mk5_harm + mk5_dis + mk5_unres
    mt5_all = mt5_harm + mt5_dis + mt5_unres

    # Bani: D2 → Bb2 → Eb2
    ba5_measures = []
    for i in range(n5):
        mb = stream.Measure()
        if i < 16:
            mb.append(make_note('D2', 2))
            mb.append(make_note('D2', 2))
        elif i < 32:
            mb.append(make_note('Bb2', 2))
            mb.append(make_note('Bb2', 2))
        else:
            mb.append(make_note('Eb2', 2))
            mb.append(make_note('Eb2', 2))
        ba5_measures.append(mb)

    gi5_measures = []
    for i in range(n5):
        mg = stream.Measure()
        mg.append(note.Rest(quarterLength=beats5))
        gi5_measures.append(mg)

    for i, (mk_m, mt_m, ba_m, gi_m) in enumerate(
            zip(mk5_all, mt5_all, ba5_measures, gi5_measures)):
        is_f = (i == 0)
        if is_f:
            rm = expressions.RehearsalMark("Song 5: Mze Shina (მზე შინა)")
            rm.style.fontSize = 11
            mk_m.insert(0, rm)
            mk_m.insert(0, meter.TimeSignature('4/4'))
            mk_m.insert(0, key.Key('d'))
            mk_m.insert(0, tempo.MetronomeMark(number=56,
                         referent=note.Note(type='quarter')))

            mt_m.insert(0, meter.TimeSignature('4/4'))
            mt_m.insert(0, key.Key('d'))
            ba_m.insert(0, meter.TimeSignature('4/4'))
            ba_m.insert(0, key.Key('d'))
            gi_m.insert(0, meter.TimeSignature('4/4'))
            gi_m.insert(0, key.Key('d'))

        if i == 16:
            # Mark key change to Bb major
            mk_m.insert(0, key.Key('B-'))
            mt_m.insert(0, key.Key('B-'))
            ba_m.insert(0, key.Key('B-'))

        part_mkrimani.append(mk_m)
        part_mtavari.append(mt_m)
        part_bani.append(ba_m)
        part_gilgamesh.append(gi_m)

    # ════════════════════════════════════════════════════════════
    # SONG 6: Alilo — 40 measures, 4/4, D major→Mixolydian, ♩=58
    # m.33-40: all four voices join
    # ════════════════════════════════════════════════════════════
    beats6 = 4.0
    n6 = 40

    mk6_measures = build_measures_from_pattern(S6_mkrimani, n6, beats6)
    mt6_measures = build_measures_from_pattern(S6_mtavari,  n6, beats6)
    ba6_measures = build_measures_from_pattern(S6_bani,     n6, beats6)

    # Gilgamesh joins only in measures 33-40
    gi6_measures = []
    for i in range(n6):
        if i < 32:
            mg = stream.Measure()
            mg.append(note.Rest(quarterLength=beats6))
            gi6_measures.append(mg)
        else:
            gi6_measures.extend(
                build_measures_from_pattern(S6_gilga, 1, beats6))

    for i, (mk_m, mt_m, ba_m, gi_m) in enumerate(
            zip(mk6_measures, mt6_measures, ba6_measures, gi6_measures)):
        is_f = (i == 0)
        if is_f:
            rm = expressions.RehearsalMark("Song 6: Alilo (ალილო)")
            rm.style.fontSize = 11
            mk_m.insert(0, rm)
            mk_m.insert(0, meter.TimeSignature('4/4'))
            mk_m.insert(0, key.Key('D'))
            mk_m.insert(0, tempo.MetronomeMark(number=58,
                         referent=note.Note(type='quarter')))

            mt_m.insert(0, meter.TimeSignature('4/4'))
            mt_m.insert(0, key.Key('D'))
            ba_m.insert(0, meter.TimeSignature('4/4'))
            ba_m.insert(0, key.Key('D'))
            gi_m.insert(0, meter.TimeSignature('4/4'))
            gi_m.insert(0, key.Key('D'))

        if i == 32:
            # Mixolydian shift (C natural instead of C#)
            mk_m.insert(0, key.Key('D', 'mixolydian'))
            mt_m.insert(0, key.Key('D', 'mixolydian'))
            ba_m.insert(0, key.Key('D', 'mixolydian'))
            gi_m.insert(0, key.Key('D', 'mixolydian'))

        # Grace notes on Mkrimani beat-1 notes in Song 6
        mk_notes = [n for n in mk_m.notes]
        if mk_notes:
            gn = make_grace('F#5')
            mk_m.insertAndShift(mk_notes[0].offset, gn)

        part_mkrimani.append(mk_m)
        part_mtavari.append(mt_m)
        part_bani.append(ba_m)
        part_gilgamesh.append(gi_m)

    # ════════════════════════════════════════════════════════════
    # LYRICS — real Georgian folk text in Latin transliteration
    # Distributed syllable-by-syllable to each non-rest note
    # ════════════════════════════════════════════════════════════

    def assign_lyrics(part, syllables, m_start=None, m_end=None):
        """Assign syllables cyclically to all non-rest notes in part
        (or within measure range [m_start, m_end) if given)."""
        measures = list(part.getElementsByClass('Measure'))
        if m_start is not None or m_end is not None:
            measures = measures[m_start:m_end]
        notes_list = []
        for m in measures:
            for n_obj in m.notes:
                if not isinstance(n_obj, chord.Chord):
                    notes_list.append(n_obj)
        idx = 0
        for n_obj in notes_list:
            n_obj.lyric = syllables[idx % len(syllables)]
            idx += 1

    # ── Song 1: Mravalzhamier (measures 0-32) ─────────────────
    lyrics_mk_s1 = [
        "mra","val","zha","mi","er","mra","val","zha","mi","er",
        "tkven","da","chve","ni","ra","tskhi","li","ga","mar","jos",
        "vi","tsa","ga","mar","jos","vi","tsa","ga","mar","jos","mra","val",
    ]
    lyrics_mt_s1 = [
        "vi","tsa","ga","mar","jos","vi","tsa","ga","mar","jos",
        "tkven","da","chve","ni","da","shvi","lis","shvi","li",
        "mra","val","zha","mi","er","mra","val","zha","mi","er",
    ]
    lyrics_ba_s1 = ["mra","val","zha","mi","er"]   # repeated drone

    lyrics_gi_s1 = [
        "mra","val","zha","mi","er","mra","val","zha","mi","er",
        "ga","mar","jos","vi","tsa","ga","mar","jos",
    ]

    # ── Song 2: Khasanbegura (measures 32-64) ─────────────────
    lyrics_mk_s2 = [
        "kha","san","be","gu","ra","kha","san","be","gu","ra",
        "ra","tskhi","li","kha","ri","ma","go","ni","gur","ja",
        "kha","san","be","gu","ra","kha","san","be","gu","ra",
    ]
    lyrics_mt_s2 = [
        "kha","san","ai","be","gu","ra","ro","kha","san","be",
        "gu","ra","ai","ra","tskhi","li","go","ni","gur","ja",
    ]
    lyrics_ba_s2 = ["kha","san","be","gu","ra"]    # repeated drone

    # ── Song 3: Tsintskaro (measures 64-96, bani silent) ──────
    lyrics_mk_s3 = [
        "tsin","tska","ro","tsin","tska","ro","ka","la","ko",
        "tsin","tska","ro","shen","i","qav","ka","la","ko",
        "ra","mshve","ni","e","ri","tsin","tska","ro","tsin","tska","ro",
    ]
    lyrics_mt_s3 = [
        "tsin","tska","ro","ai","tsin","tska","ro","ka","la",
        "ko","ai","ra","mshve","ni","e","ri","tsin","tska","ro",
    ]
    # bani has rests in song 3 — no lyrics assigned

    # ── Song 4: Beri Berikaoba (measures 96-128) ──────────────
    lyrics_mk_s4 = [
        "be","ri","be","ri","ka","o","ba","be","ri",
        "be","ri","ka","o","ba","ga","mar","jos","be","ri",
        "be","ri","ka","o","ba","ai","be","ri","ka","o","ba",
    ]
    lyrics_mt_s4 = [
        "be","ri","ka","o","ba","ai","be","ri","ka",
        "o","ba","ga","mar","jos","be","ri","ka","o","ba",
    ]
    lyrics_ba_s4 = ["be","ri","ka","o","ba"]       # repeated, staccato feel

    # ── Song 5: Mze Shina (measures 128-168) ──────────────────
    # Harmonic phase (m.128-144) — sweet
    lyrics_mk_s5_harm = [
        "mze","shi","na","mze","shi","na","mo","di","na",
        "mze","shi","na","da","i","ko","neb","is","tvis",
        "mze","shi","na","mo","di","na","mze","shi","na",
    ]
    # Dissonance phase (m.144-168) — text breaks, Enkidu enters
    lyrics_mk_s5_dis = [
        "en","ki","du","en","ki","du","sa","idan","me",
        "ai","en","ki","du","ra","to","tsa","mze","shi","na",
    ]
    lyrics_mt_s5_harm = [
        "mze","shi","na","mze","shi","na","mo","di","na",
        "mze","shi","na","da","i","ko","neb","is","tvis",
        "mze","shi","na","mo","di","na","mze","shi","na",
    ]
    lyrics_mt_s5_dis = [
        "en","ki","du","en","ki","du","sa","idan","me",
        "ai","en","ki","du","ra","to","tsa","mze","shi","na",
    ]
    lyrics_ba_s5_harm = ["mze","shi","na"]
    lyrics_ba_s5_dis  = ["ai","ra","to"]

    # Song 5 — assign harmonic and dissonant phases separately
    assign_lyrics(part_mkrimani, lyrics_mk_s5_harm, m_start=128, m_end=144)
    assign_lyrics(part_mkrimani, lyrics_mk_s5_dis,  m_start=144, m_end=168)
    assign_lyrics(part_mtavari,  lyrics_mt_s5_harm, m_start=128, m_end=144)
    assign_lyrics(part_mtavari,  lyrics_mt_s5_dis,  m_start=144, m_end=168)
    assign_lyrics(part_bani,     lyrics_ba_s5_harm, m_start=128, m_end=144)
    assign_lyrics(part_bani,     lyrics_ba_s5_dis,  m_start=144, m_end=168)

    # ── Song 6: Alilo (measures 168-208) ──────────────────────
    lyrics_mk_s6 = [
        "a","li","lo","a","li","lo","kris","tes","a",
        "a","li","lo","ra","shei","qmna","kris","te","si",
        "a","li","lo","mshvi","do","ba","da","si","kha",
        "ru","le","a","li","lo","kris","tes","a","a","li","lo",
    ]
    lyrics_mt_s6 = [
        "a","li","lo","ai","a","li","lo","a","li",
        "lo","ai","kris","tes","a","ra","shei","qmna","a","li","lo",
    ]
    lyrics_ba_s6 = ["a","li","lo","kris","tes","a"]   # repeated drone
    lyrics_gi_s6 = [
        "a","li","lo","a","li","lo","u","ru","ki",
        "mat","li","sa","kha","ri","li","a","li","lo",
    ]

    # ── Assign all lyrics (except Song 5 assigned above) ──────
    assign_lyrics(part_mkrimani, lyrics_mk_s1, m_start=0,   m_end=32)
    assign_lyrics(part_mtavari,  lyrics_mt_s1, m_start=0,   m_end=32)
    assign_lyrics(part_bani,     lyrics_ba_s1, m_start=0,   m_end=32)
    assign_lyrics(part_gilgamesh,lyrics_gi_s1, m_start=0,   m_end=32)

    assign_lyrics(part_mkrimani, lyrics_mk_s2, m_start=32,  m_end=64)
    assign_lyrics(part_mtavari,  lyrics_mt_s2, m_start=32,  m_end=64)
    assign_lyrics(part_bani,     lyrics_ba_s2, m_start=32,  m_end=64)

    assign_lyrics(part_mkrimani, lyrics_mk_s3, m_start=64,  m_end=96)
    assign_lyrics(part_mtavari,  lyrics_mt_s3, m_start=64,  m_end=96)
    # bani rests in song 3 — no lyrics

    assign_lyrics(part_mkrimani, lyrics_mk_s4, m_start=96,  m_end=128)
    assign_lyrics(part_mtavari,  lyrics_mt_s4, m_start=96,  m_end=128)
    assign_lyrics(part_bani,     lyrics_ba_s4, m_start=96,  m_end=128)

    # Song 5 already assigned above

    assign_lyrics(part_mkrimani, lyrics_mk_s6, m_start=168, m_end=208)
    assign_lyrics(part_mtavari,  lyrics_mt_s6, m_start=168, m_end=208)
    assign_lyrics(part_bani,     lyrics_ba_s6, m_start=168, m_end=208)
    assign_lyrics(part_gilgamesh,lyrics_gi_s6, m_start=200, m_end=208)  # joins m.33-40 only

    # ════════════════════════════════════════════════════════════
    # FINAL BAR LINES
    # ════════════════════════════════════════════════════════════
    for part in [part_mkrimani, part_mtavari, part_bani, part_gilgamesh]:
        final_m = part.getElementsByClass('Measure')[-1]
        final_m.rightBarline = bar.Barline('final')

    # ════════════════════════════════════════════════════════════
    # ASSEMBLE SCORE
    # ════════════════════════════════════════════════════════════
    sc.insert(0, part_mkrimani)
    sc.insert(0, part_mtavari)
    sc.insert(0, part_bani)
    sc.insert(0, part_gilgamesh)

    return sc


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("Building Krimanchuli Trio score...")
    sc = build_score()

    print(f"Writing to: {OUT_FILE}")
    sc.write('musicxml', fp=OUT_FILE)

    size = os.path.getsize(OUT_FILE)
    print(f"Done. File size: {size:,} bytes ({size/1024:.1f} KB)")
    print(f"Parts: {len(sc.parts)}")
    total_measures = sum(len(p.getElementsByClass('Measure')) for p in sc.parts)
    print(f"Total measures (all parts): {total_measures}")
    expected = (32 + 32 + 32 + 32 + 40 + 40) * 4
    print(f"Expected measure-slots: {expected} (208 measures × 4 parts)")
