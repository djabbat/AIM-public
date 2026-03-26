#!/usr/bin/env python3
"""
ŠAMNU AZUZI v3 — COMPLETE OPERA FOR MUSESCORE 3
სამნუ ა-ზუ-ზი / Samnu A-zu-zi
Music and Libretto: Jaba Tkemaladze
~210 minutes · 5 Acts · 17 Scenes · 1573 measures

VERSION 3 PRINCIPLES:
  · All 20 themes T1–T20 — EXACT note sequences from specification
  · English lyrics on all vocal parts
  · NO SILENCE ANYWHERE — piano+strings always play; inactive voices drone
  · Long developmental arcs — hypnotic, not wave-like
  · Act I=238, Act II=335, Act III=245, Act IV=274, Act V=481 (TOTAL=1573)
"""

import os
import copy

from music21 import (
    stream, note, chord, tempo, meter, key, dynamics,
    expressions, metadata, instrument, clef, bar, pitch
)

OUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "SAMNU_AZUZI_v3.musicxml")

# ══════════════════════════════════════════════════════════════════════
# EXACT THEMES T1–T20 — do NOT alter note sequences
# Format: list of (pitch_or_R, quarter_duration)
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
# LYRICS — English syllables for every theme and section
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
}

# ══════════════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════════════

VALID_DURS = {4.0, 3.0, 2.0, 1.5, 1.0, 0.75, 0.5, 0.25}

def _snap_dur(d):
    """Snap duration to nearest valid value."""
    candidates = sorted(VALID_DURS)
    best = candidates[0]
    for c in candidates:
        if abs(c - d) < abs(best - d):
            best = c
    return best

def N(p, dur=1.0, lyr=None, dyn_str=None, oct_shift=0, fermata=False):
    """Create a note or rest. p='R' for rest."""
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
    """Convert [(pitch,dur),...] → [Note/Rest,...] with optional lyrics/dynamics."""
    out = []
    for i, (p, d) in enumerate(pitch_dur_list):
        lyr = lyrics[i] if lyrics and i < len(lyrics) else None
        d0 = dyn if i == 0 else None
        fe = (i == len(pitch_dur_list) - 1)  # fermata on last note only if needed
        out.append(N(p, d, lyr=lyr, dyn_str=d0, oct_shift=oct_shift))
    return out

def _ts_beats(ts_str):
    """Return total quarter-note beats in one measure of ts_str."""
    num, den = map(int, ts_str.split('/'))
    return num * (4.0 / den)

def _split_note_for_beats(p, dur, remaining):
    """
    If dur > remaining, split into (remaining) + (dur-remaining).
    Returns list of notes/rests.
    Uses only valid durations; ties the first if needed.
    """
    result = []
    while dur > 1e-9:
        take = min(dur, remaining)
        take = _snap_dur(take)
        if take < 0.24:
            take = 0.25
        if p == 'R':
            n = note.Rest(quarterLength=take)
        else:
            n = note.Note(p, quarterLength=take)
        result.append(n)
        dur -= take
        dur = round(dur, 6)
        remaining -= take
        remaining = round(remaining, 6)
        if remaining < 1e-9:
            break
    return result

def pack_to_measures(notes_list, ts_str, ks=None, bpm=None, txt=None):
    """
    Pack a flat list of notes/rests into Measure objects of ts_str.
    Returns list of Measure objects.
    """
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
                # keep lyric only on first segment
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

    # flush partial measure
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
    """
    Repeat notes_list until exactly n_measures of ts_str are filled.
    Returns exactly n_measures Measure objects.
    """
    beats_per = _ts_beats(ts_str)
    total_needed = n_measures * beats_per

    # Calculate total beats in one pass of notes_list
    pass_beats = sum(round(float(x.quarterLength), 6) for x in notes_list)
    if pass_beats < 1e-9:
        pass_beats = beats_per

    # How many full+partial repeats needed
    repeats = int(total_needed / pass_beats) + 2
    big_list = []
    for _ in range(repeats):
        big_list.extend(copy.deepcopy(notes_list))

    all_measures = pack_to_measures(big_list, ts_str, ks=ks, bpm=bpm, txt=txt)
    # Trim or pad to exactly n_measures
    result = all_measures[:n_measures]
    while len(result) < n_measures:
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        m.append(note.Rest(quarterLength=beats_per))
        result.append(m)
    return result

def rests_split(n_measures, ts_str='4/4'):
    """Create n_measures of rests in ts_str."""
    beats_per = _ts_beats(ts_str)
    result = []
    for _ in range(n_measures):
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        rem = beats_per
        while rem > 1e-9:
            d = _snap_dur(rem)
            if d > rem + 1e-6:
                d = _snap_dur(rem * 0.9)
            if d < 0.24:
                d = 0.25
            m.append(note.Rest(quarterLength=d))
            rem = round(rem - d, 6)
        result.append(m)
    return result

def drone_fill(part, pitch_str, n_measures, ts_str='4/4', dyn='ppp', lyr='aah'):
    """
    Fill part with n_measures of a sustained drone on pitch_str.
    Drone note = one whole measure (split if compound).
    """
    beats_per = _ts_beats(ts_str)
    for i in range(n_measures):
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        rem = beats_per
        first = True
        while rem > 1e-9:
            d = _snap_dur(rem)
            if d > rem + 1e-6:
                d = _snap_dur(rem * 0.9)
            if d < 0.24:
                d = 0.25
            n0 = note.Note(pitch_str, quarterLength=d)
            if first and i == 0:
                n0.expressions.append(dynamics.Dynamic(dyn))
                if lyr:
                    n0.addLyric(lyr)
                first = False
            part.append(m)  # placeholder; we build below
            rem = round(rem - d, 6)
        # Redo properly
        part.elements  # force evaluation — just reference
        break  # exit; we'll use the proper approach below

    # Proper approach: build measures directly
    # (Remove the placeholder added above)
    # Clear what was appended
    # Actually build cleanly
    pass

def _build_drone_measures(pitch_str, n_measures, ts_str='4/4', dyn='ppp', lyr='aah'):
    """Return list of Measure objects filled with drone on pitch_str."""
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
    """Return list of n_measures of full rests."""
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
    """
    Return list of n_measures with piano harmonic block chords.
    One chord per beat, repeated.
    """
    beats_per = _ts_beats(ts_str)
    beats_int = int(round(beats_per))
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
    """
    Return list of n_measures with sustained string chord.
    One chord per measure (split into valid durations).
    """
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
    """Append a list of Measure objects to a Part."""
    for m in measures_list:
        part.append(m)

# ══════════════════════════════════════════════════════════════════════
# PART CREATION
# ══════════════════════════════════════════════════════════════════════

def make_part(name, inst_obj, midi_channel=1):
    """Create a Part with instrument and name."""
    p = stream.Part()
    p.id = name.replace(' ', '_')
    p.partName = name
    inst_obj.midiChannel = midi_channel
    p.insert(0, inst_obj)
    return p

# ══════════════════════════════════════════════════════════════════════
# SCENE BUILDER — builds one scene across all 17 parts
# ══════════════════════════════════════════════════════════════════════

def build_scene(scene_data, parts_dict):
    """
    scene_data: dict with keys:
      n_measures, ts_str, ks_int, bpm, label,
      featured: {part_name: [(theme_data, lyrics, dyn, repeats), ...]}
      piano_chords: [pitch_list]  — what piano plays (chord pitches)
      strings_pitches: [pitch_list] — what strings sustain
      drone_pitch: str  — tonic pitch for inactive voices
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

    # Build each part
    for pname, part in parts_dict.items():
        if pname == 'Piano':
            ms = piano_harmony(piano_chords_p, n, ts, dyn='pp')
            if ms:
                ms[0].insert(0, meter.TimeSignature(ts))
                ms[0].insert(0, key.KeySignature(ks))
                ms[0].insert(0, tempo.MetronomeMark(number=bpm_val))
                if label:
                    ms[0].insert(0, expressions.TextExpression(label))
            add_measures(part, ms)

        elif pname == 'Strings':
            ms = strings_sustain(str_p, n, ts, dyn='pp')
            if ms:
                ms[0].insert(0, meter.TimeSignature(ts))
                ms[0].insert(0, key.KeySignature(ks))
            add_measures(part, ms)

        elif pname in featured:
            # Build featured content
            feat_list = featured[pname]  # list of (notes_list, lyrics, dyn, repeats)
            all_notes = []
            for (nlist, lyrs, dyn_s, reps) in feat_list:
                nl = theme_notes(nlist, lyrics=lyrs, dyn=dyn_s)
                for _ in range(reps):
                    all_notes.extend(copy.deepcopy(nl))

            ms = repeat_fill(all_notes, n, ts, ks=ks)
            if ms:
                ms[0].insert(0, meter.TimeSignature(ts))
                ms[0].insert(0, key.KeySignature(ks))
                if pname not in ('Piano', 'Strings'):
                    pass  # bpm already on measure 1 of piano
            add_measures(part, ms)

        else:
            # Inactive voice — drone
            if pname in ('Lamuri',):
                # Lamuri always plays ppp D4 drone when not featured
                drone_note = 'D4'
                ms = _build_drone_measures(drone_note, n, ts, dyn='ppp', lyr=None)
            elif pname in ('Chuniri', 'Panduri'):
                ms = _build_drone_measures(drone_p, n, ts, dyn='ppp', lyr=None)
            elif pname in ('Winds', 'Brass', 'Cello'):
                ms = _build_drone_measures(drone_p, n, ts, dyn='ppp', lyr=None)
            else:
                # Vocal parts — drone on tonic with 'aah'
                ms = _build_drone_measures(drone_p, n, ts, dyn='ppp', lyr='aah')
            if ms:
                ms[0].insert(0, meter.TimeSignature(ts))
                ms[0].insert(0, key.KeySignature(ks))
            add_measures(part, ms)

# ══════════════════════════════════════════════════════════════════════
# MAIN SCORE ASSEMBLY
# ══════════════════════════════════════════════════════════════════════

def build_score():
    sc = stream.Score()

    # Metadata
    md = metadata.Metadata()
    md.title = 'Šamnu Azuzi (სამნუ ა-ზუ-ზი)'
    md.composer = 'Jaba Tkemaladze'
    sc.insert(0, md)

    # ── Parts (17 total) ──────────────────────────────────────────────
    parts = {}

    def mp(name, inst_cls, ch):
        p = make_part(name, inst_cls(), ch)
        parts[name] = p
        return p

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

    # ══════════════════════════════════════════════════════════════════
    # ACT I — 238 measures total
    # Scene 1: 80m, Scene 2: 82m, Scene 3: 76m
    # ══════════════════════════════════════════════════════════════════

    # ── SCENE 1: 80 measures, G minor (ks=-2), 5/8, ♩=58 ─────────────
    # T16 Chorus (Beri-Berikoba), Gilgamesh arioso, Trio MK/MT/BN T1
    T16_notes = theme_notes(T16_chorus, lyrics=LYR['T16'], dyn='mf')
    T1_mk_notes = theme_notes(T1_mkrimani, lyrics=LYR['T1'], dyn='ppp')
    T1_mt_notes = theme_notes(T1_mtavari, lyrics=LYR['T1'], dyn='ppp')
    T1_bn_notes = theme_notes(T1_bani, lyrics=LYR['T2_bn'], dyn='ppp')
    gil_ar = theme_notes(
        [('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',0.5),('G4',0.5),
         ('F4',1),('E4',0.5),('D4',0.5),('C4',1),('D4',0.5),('E4',0.5),
         ('F4',1),('G4',1),('A4',0.5),('Bb4',0.5),('A4',0.5),('G4',0.5)],
        lyrics=LYR['gil_arioso'], dyn='f'
    )

    sc1 = {
        'n_measures': 80, 'ts_str': '5/8', 'ks_int': -2, 'bpm': 58,
        'label': 'ACT I — Scene 1: Uruk, oppressed',
        'piano_chords': ['G2','Bb2','D3','G3'],
        'strings_pitches': ['G2','D3','G3'],
        'drone_pitch': 'G4',
        'featured': {
            'Chorus':    [(T16_chorus, LYR['T16'], 'mf', 1)],
            'Gilgamesh': [([('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',0.5),('G4',0.5),
                            ('F4',1),('E4',0.5),('D4',0.5),('C4',1),('D4',0.5),('E4',0.5),
                            ('F4',1),('G4',1),('A4',0.5),('Bb4',0.5),('A4',0.5),('G4',0.5)],
                           LYR['gil_arioso'], 'f', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'ppp', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'ppp', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'ppp', 1)],
        }
    }
    build_scene(sc1, parts)

    # ── SCENE 2: 82 measures, D minor (ks=-1), 4/4, ♩=66 ─────────────
    # T16 builds, Enkidu awakens T6, Ninsun T7 lullaby
    sc2 = {
        'n_measures': 82, 'ts_str': '4/4', 'ks_int': -1, 'bpm': 66,
        'label': 'Scene 2: Enkidu awakens',
        'piano_chords': ['D2','F2','A2','D3'],
        'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4',
        'featured': {
            'Chorus':    [(T16_chorus, LYR['T16'], 'f', 1)],
            'Enkidu':    [(T6_enkidu, LYR['enkidu_first'], 'p', 1)],
            'Ninsun':    [(T7_ninsun, LYR['T7'], 'mp', 1)],
            'Lamuri':    [(T4_lamuri, None, 'p', 1)],
            'Chuniri':   [(T7_chuniri, None, 'p', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'ppp', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'ppp', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'ppp', 1)],
        }
    }
    build_scene(sc2, parts)

    # ── SCENE 3: 76 measures, A minor (ks=0), 4/4, ♩=72 ─────────────
    # Shamhat appears T12, Trio T1 grows
    sc3 = {
        'n_measures': 76, 'ts_str': '4/4', 'ks_int': 0, 'bpm': 72,
        'label': 'Scene 3: Shamhat, the sacred',
        'piano_chords': ['A2','C3','E3','A3'],
        'strings_pitches': ['A2','E3','A3'],
        'drone_pitch': 'A4',
        'featured': {
            'Shamhat':   [(T12_shamhat, LYR['T12'], 'mf', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'mp', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'mp', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'mp', 1)],
            'Lamuri':    [(T5_lamuri, None, 'mp', 1)],
            'Panduri':   [(T5_panduri, None, 'mp', 1)],
            'Chorus':    [(T16_chorus, LYR['T16'], 'ff', 1)],
        }
    }
    build_scene(sc3, parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT II — 335 measures total
    # Scene 4: 84m, Scene 5: 84m, Scene 6: 84m, Scene 7: 83m
    # ══════════════════════════════════════════════════════════════════

    # ── SCENE 4: 84m, D major (ks=2), 4/4, ♩=76 ─────────────────────
    # Enkidu meets Gilgamesh — T13 duet, T1 Trio
    sc4 = {
        'n_measures': 84, 'ts_str': '4/4', 'ks_int': 2, 'bpm': 76,
        'label': 'ACT II — Scene 4: The meeting',
        'piano_chords': ['D2','F#2','A2','D3'],
        'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4',
        'featured': {
            'Shamhat':   [(T13_shamhat, LYR['T13_sh'], 'mf', 1)],
            'Enkidu':    [(T13_enkidu, LYR['T13_ek'], 'mf', 1)],
            'Gilgamesh': [([('D4',1),('F#4',0.5),('A4',0.5),('D5',1),('C#5',0.5),('D5',0.5),
                            ('A4',1),('F#4',1),('D4',2)],
                           LYR['brothers'], 'f', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'mp', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'mp', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'mp', 1)],
            'Chorus':    [(T18_chorus, LYR['T18'], 'mf', 1)],
            'Lamuri':    [(T5_lamuri, None, 'mp', 1)],
        }
    }
    build_scene(sc4, parts)

    # ── SCENE 5: 84m, D major (ks=2), 5/8, ♩=88 ─────────────────────
    # Wrestling match — T15 Khasanbegura battle
    sc5 = {
        'n_measures': 84, 'ts_str': '5/8', 'ks_int': 2, 'bpm': 88,
        'label': 'Scene 5: The wrestling',
        'piano_chords': ['D2','A2','D3','F#3'],
        'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4',
        'featured': {
            'Gilgamesh': [(T15_orch, LYR['T15'], 'ff', 1)],
            'Enkidu':    [(T15_orch, LYR['T15'], 'ff', 1)],
            'Chorus':    [(T15_orch, LYR['T15'], 'fff', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'mf', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'mf', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'mf', 1)],
            'Winds':     [(T15_orch, None, 'ff', 1)],
            'Brass':     [(T15_orch, None, 'fff', 1)],
        }
    }
    build_scene(sc5, parts)

    # ── SCENE 6: 84m, G major (ks=1), 4/4, ♩=72 ─────────────────────
    # Brotherhood sworn — T17 Mravalzhamier
    sc6 = {
        'n_measures': 84, 'ts_str': '4/4', 'ks_int': 1, 'bpm': 72,
        'label': 'Scene 6: Brotherhood sworn',
        'piano_chords': ['G2','B2','D3','G3'],
        'strings_pitches': ['G2','D3','G3'],
        'drone_pitch': 'G4',
        'featured': {
            'Gilgamesh': [(T17_trio, LYR['T17'], 'f', 1)],
            'Enkidu':    [(T17_trio, LYR['T17'], 'f', 1)],
            'Mkrimani':  [(T17_trio, LYR['T17'], 'mf', 1)],
            'Mtavari':   [(T17_trio, LYR['T17'], 'mf', 1)],
            'Bani':      [(T17_trio, LYR['T17'], 'mf', 1)],
            'Chorus':    [(T17_trio, LYR['T17'], 'ff', 1)],
            'Ninsun':    [(T7_ninsun, LYR['T7'], 'mp', 1)],
            'Lamuri':    [(T5_lamuri, None, 'mp', 1)],
        }
    }
    build_scene(sc6, parts)

    # ── SCENE 7: 83m, D minor (ks=-1), 7/8, ♩=60 ────────────────────
    # Journey to Cedar Forest — T4 Lamuri, T19 Humbaba distant
    sc7 = {
        'n_measures': 83, 'ts_str': '7/8', 'ks_int': -1, 'bpm': 60,
        'label': 'Scene 7: Journey to the forest',
        'piano_chords': ['D2','F2','A2','D3'],
        'strings_pitches': ['D2','F2','A2'],
        'drone_pitch': 'D4',
        'featured': {
            'Lamuri':    [(T4_lamuri, None, 'mp', 1)],
            'Humbaba_Utnapishti': [(T19_humbaba, LYR['T19'], 'ppp', 1)],
            'Gilgamesh': [([('D4',1),('F4',0.5),('A4',0.5),('C5',1),('A4',0.5),('F4',0.5),
                            ('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',2)],
                           LYR['shadows'], 'mp', 1)],
            'Enkidu':    [(T6_enkidu, LYR['enkidu_first'], 'mp', 1)],
            'Chuniri':   [(T7_chuniri, None, 'p', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'pp', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'pp', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'pp', 1)],
        }
    }
    build_scene(sc7, parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT III — 245 measures total
    # Scene 8: 82m, Scene 9: 82m, Scene 10: 81m
    # ══════════════════════════════════════════════════════════════════

    # ── SCENE 8: 82m, C# minor (ks=4), 4/4, ♩=54 ────────────────────
    # Humbaba confrontation — T19 dominates
    sc8 = {
        'n_measures': 82, 'ts_str': '4/4', 'ks_int': 4, 'bpm': 54,
        'label': 'ACT III — Scene 8: Humbaba',
        'piano_chords': ['C#2','E2','G#2','C#3'],
        'strings_pitches': ['C#2','G#2','C#3'],
        'drone_pitch': 'C#4',
        'featured': {
            'Humbaba_Utnapishti': [(T19_humbaba, LYR['T19'], 'ff', 1)],
            'Gilgamesh': [(T15_orch, LYR['T15'], 'f', 1)],
            'Enkidu':    [(T15_orch, LYR['T15'], 'f', 1)],
            'Chorus':    [(T16_chorus, LYR['T16'], 'mf', 1)],
            'Brass':     [(T19_humbaba, None, 'ff', 1)],
            'Mkrimani':  [(T2_mkrimani, LYR['T2_mk'], 'mp', 1)],
            'Mtavari':   [(T2_mtavari, LYR['T2_mt'], 'mp', 1)],
            'Bani':      [(T2_bani, LYR['T2_bn'], 'mp', 1)],
        }
    }
    build_scene(sc8, parts)

    # ── SCENE 9: 82m, A minor (ks=0), 5/8, ♩=66 ─────────────────────
    # Battle peaks — T15 + T20 Chakrulo
    sc9 = {
        'n_measures': 82, 'ts_str': '5/8', 'ks_int': 0, 'bpm': 66,
        'label': 'Scene 9: The battle',
        'piano_chords': ['A2','C3','E3','A3'],
        'strings_pitches': ['A2','E3','A3'],
        'drone_pitch': 'A4',
        'featured': {
            'Gilgamesh': [(T20_orch, LYR['T20'], 'fff', 1)],
            'Enkidu':    [(T20_orch, LYR['T20'], 'fff', 1)],
            'Chorus':    [(T20_orch, LYR['T20'], 'fff', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
            'Winds':     [(T15_orch, None, 'ff', 1)],
            'Mkrimani':  [(T2_mkrimani, LYR['T2_mk'], 'mf', 1)],
            'Mtavari':   [(T2_mtavari, LYR['T2_mt'], 'mf', 1)],
            'Bani':      [(T2_bani, LYR['T2_bn'], 'mf', 1)],
        }
    }
    build_scene(sc9, parts)

    # ── SCENE 10: 81m, D major (ks=2), 4/4, ♩=80 ─────────────────────
    # Victory — T3 Alilo, T17 Mravalzhamier
    sc10 = {
        'n_measures': 81, 'ts_str': '4/4', 'ks_int': 2, 'bpm': 80,
        'label': 'Scene 10: Victory, Alilo',
        'piano_chords': ['D2','F#2','A2','D3'],
        'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4',
        'featured': {
            'Mkrimani':  [(T3_mkrimani, LYR['T3'], 'ff', 1)],
            'Mtavari':   [(T3_mtavari, LYR['T3'], 'ff', 1)],
            'Bani':      [(T3_bani, LYR['T3'], 'ff', 1)],
            'Chorus':    [(T17_trio, LYR['T17'], 'fff', 1)],
            'Gilgamesh': [(T17_trio, LYR['T17'], 'f', 1)],
            'Enkidu':    [(T17_trio, LYR['T17'], 'f', 1)],
            'Brass':     [(T20_orch, None, 'ff', 1)],
            'Lamuri':    [(T5_lamuri, None, 'f', 1)],
        }
    }
    build_scene(sc10, parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT IV — 274 measures total
    # Scene 11: 92m, Scene 12: 91m, Scene 13: 91m
    # ══════════════════════════════════════════════════════════════════

    # ── SCENE 11: 92m, Bb major (ks=-2), 7/8, ♩=58 ──────────────────
    # Bull of Heaven — T20 Chakrulo, Ninsun T8
    sc11 = {
        'n_measures': 92, 'ts_str': '7/8', 'ks_int': -2, 'bpm': 58,
        'label': 'ACT IV — Scene 11: Bull of Heaven',
        'piano_chords': ['Bb2','D3','F3','Bb3'],
        'strings_pitches': ['Bb2','F3','Bb3'],
        'drone_pitch': 'Bb4',
        'featured': {
            'Chorus':    [(T20_orch, LYR['T20'], 'fff', 1)],
            'Gilgamesh': [(T20_orch, LYR['T20'], 'ff', 1)],
            'Enkidu':    [(T20_orch, LYR['T20'], 'ff', 1)],
            'Ninsun':    [(T8_ninsun, LYR['T8'], 'mp', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
            'Winds':     [(T20_orch, None, 'ff', 1)],
            'Mkrimani':  [(T2_mkrimani, LYR['T2_mk'], 'mf', 1)],
            'Mtavari':   [(T2_mtavari, LYR['T2_mt'], 'mf', 1)],
            'Bani':      [(T2_bani, LYR['T2_bn'], 'mf', 1)],
        }
    }
    build_scene(sc11, parts)

    # ── SCENE 12: 91m, D minor (ks=-1), 4/4, ♩=50 ───────────────────
    # Enkidu's illness — T6 Virishkhau, T7 Ninsun
    sc12 = {
        'n_measures': 91, 'ts_str': '4/4', 'ks_int': -1, 'bpm': 50,
        'label': 'Scene 12: Enkidu falls ill',
        'piano_chords': ['D2','F2','A2','C3'],
        'strings_pitches': ['D2','F2','A2'],
        'drone_pitch': 'D4',
        'featured': {
            'Enkidu':    [(T6_enkidu, LYR['enkidu_first'], 'pp', 1)],
            'Lamuri':    [(T6_lamuri, None, 'ppp', 1)],
            'Ninsun':    [(T7_ninsun, LYR['T7'], 'mp', 1)],
            'Chuniri':   [(T7_chuniri, None, 'p', 1)],
            'Gilgamesh': [([('D4',2),('F4',1),('A4',1),('G4',2),('F4',1),('E4',1),('D4',4)],
                           LYR['lament'], 'mf', 1)],
            'Shamhat':   [(T14_shamhat, LYR['T14'], 'f', 1)],
            'Mkrimani':  [(T2_mkrimani, LYR['T2_mk'], 'pp', 1)],
            'Mtavari':   [(T2_mtavari, LYR['T2_mt'], 'pp', 1)],
            'Bani':      [(T2_bani, LYR['T2_bn'], 'pp', 1)],
        }
    }
    build_scene(sc12, parts)

    # ── SCENE 13: 91m, A minor (ks=0), 4/4, ♩=46 ────────────────────
    # Enkidu's death — T6 Lamuri dying, T9 Ninsun Odoia
    sc13 = {
        'n_measures': 91, 'ts_str': '4/4', 'ks_int': 0, 'bpm': 46,
        'label': 'Scene 13: Enkidu dies',
        'piano_chords': ['A2','C3','E3','G3'],
        'strings_pitches': ['A2','C3','E3'],
        'drone_pitch': 'A4',
        'featured': {
            'Enkidu':    [(T6_enkidu, LYR['enkidu_first'], 'ppp', 1)],
            'Lamuri':    [(T6_lamuri, None, 'ppp', 1)],
            'Ninsun':    [(T9_ninsun, LYR['T9'], 'mp', 1)],
            'Gilgamesh': [([('A4',2),('G4',1),('F4',1),('E4',2),('D4',1),('C4',1),('A3',4)],
                           LYR['lament'], 'ff', 1)],
            'Shamhat':   [(T14_shamhat, LYR['T14'], 'mf', 1)],
            'Mkrimani':  [(T2_mkrimani, LYR['T2_mk'], 'p', 1)],
            'Mtavari':   [(T2_mtavari, LYR['T2_mt'], 'p', 1)],
            'Bani':      [(T2_bani, LYR['T2_bn'], 'p', 1)],
            'Chorus':    [(T11_alto, LYR['T11_al'], 'pp', 1)],
        }
    }
    build_scene(sc13, parts)

    # ══════════════════════════════════════════════════════════════════
    # ACT V — 481 measures total
    # Scene 14: 100m, Scene 15: 97m, Scene 16: 100m, Scene 17: 184m
    # ══════════════════════════════════════════════════════════════════

    # ── SCENE 14: 100m, D minor (ks=-1), 4/4, ♩=44 ──────────────────
    # Gilgamesh's lament / wandering — T10 Ninsun Samkurao
    sc14 = {
        'n_measures': 100, 'ts_str': '4/4', 'ks_int': -1, 'bpm': 44,
        'label': 'ACT V — Scene 14: Gilgamesh wanders',
        'piano_chords': ['D2','F2','A2','D3'],
        'strings_pitches': ['D2','F2','A2'],
        'drone_pitch': 'D4',
        'featured': {
            'Gilgamesh': [([('D4',2),('E4',1),('F4',1),('G4',2),('A4',1),('Bb4',1),
                            ('A4',2),('G4',1),('F4',1),('E4',2),('D4',4)],
                           LYR['lament'], 'f', 1)],
            'Ninsun':    [(T10_ninsun, LYR['T10'], 'mp', 1)],
            'Lamuri':    [(T4_lamuri, None, 'ppp', 1)],
            'Mkrimani':  [(T2_mkrimani, LYR['T2_mk'], 'pp', 1)],
            'Mtavari':   [(T2_mtavari, LYR['T2_mt'], 'pp', 1)],
            'Bani':      [(T2_bani, LYR['T2_bn'], 'pp', 1)],
            'Chorus':    [(T11_sop1, LYR['T11_s1'], 'pp', 1)],
        }
    }
    build_scene(sc14, parts)

    # ── SCENE 15: 97m, C# minor (ks=4), 4/4, ♩=52 ───────────────────
    # Journey to Utnapishti — T19 Humbaba theme returns
    sc15 = {
        'n_measures': 97, 'ts_str': '4/4', 'ks_int': 4, 'bpm': 52,
        'label': 'Scene 15: To Utnapishti',
        'piano_chords': ['C#2','E2','G#2','B2'],
        'strings_pitches': ['C#2','G#2','B2'],
        'drone_pitch': 'C#4',
        'featured': {
            'Gilgamesh': [(T19_humbaba, LYR['T19'], 'mf', 1)],
            'Humbaba_Utnapishti': [(T19_humbaba, LYR['T19'], 'f', 1)],
            'Lamuri':    [(T4_lamuri, None, 'pp', 1)],
            'Ninsun':    [(T9_ninsun, LYR['T9'], 'p', 1)],
            'Mkrimani':  [(T2_mkrimani, LYR['T2_mk'], 'mf', 1)],
            'Mtavari':   [(T2_mtavari, LYR['T2_mt'], 'mf', 1)],
            'Bani':      [(T2_bani, LYR['T2_bn'], 'mf', 1)],
            'Chorus':    [(T16_chorus, LYR['T16'], 'pp', 1)],
        }
    }
    build_scene(sc15, parts)

    # ── SCENE 16: 100m, G minor (ks=-2), 4/4, ♩=56 ──────────────────
    # Utnapishti reveals truth — T11 Lile women, T18 Rekhviashi
    sc16 = {
        'n_measures': 100, 'ts_str': '4/4', 'ks_int': -2, 'bpm': 56,
        'label': 'Scene 16: The secret of the flood',
        'piano_chords': ['G2','Bb2','D3','F3'],
        'strings_pitches': ['G2','Bb2','D3'],
        'drone_pitch': 'G4',
        'featured': {
            'Humbaba_Utnapishti': [(T18_chorus, LYR['T18'], 'f', 1)],
            'Chorus':    [(T11_sop1, LYR['T11_s1'], 'mf', 1)],
            'Ninsun':    [(T11_alto, LYR['T11_al'], 'mp', 1)],
            'Shamhat':   [(T11_sop2, LYR['T11_s2'], 'mp', 1)],
            'Gilgamesh': [(T18_chorus, LYR['T18'], 'mp', 1)],
            'Mkrimani':  [(T1_mkrimani, LYR['T1'], 'mp', 1)],
            'Mtavari':   [(T1_mtavari, LYR['T1'], 'mp', 1)],
            'Bani':      [(T1_bani, LYR['T2_bn'], 'mp', 1)],
            'Lamuri':    [(T5_lamuri, None, 'mp', 1)],
        }
    }
    build_scene(sc16, parts)

    # ── SCENE 17: 184m, D major (ks=2), 4/4 → 5/8 → 4/4, ♩=60→72→88 ─
    # Grand finale — T3 Alilo, T17 Mravalzhamier, T1 Trio resolution
    # Split into 3 subsections: 61 + 62 + 61 measures
    # Sub-scene 17a: 61m, 4/4, ♩=60 — T3 returns
    sc17a = {
        'n_measures': 61, 'ts_str': '4/4', 'ks_int': 2, 'bpm': 60,
        'label': 'Scene 17: The return — Finale begins',
        'piano_chords': ['D2','F#2','A2','D3'],
        'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4',
        'featured': {
            'Mkrimani':  [(T3_mkrimani, LYR['T3'], 'mf', 1)],
            'Mtavari':   [(T3_mtavari, LYR['T3'], 'mf', 1)],
            'Bani':      [(T3_bani, LYR['T3'], 'mf', 1)],
            'Gilgamesh': [(T17_trio, LYR['T17'], 'f', 1)],
            'Ninsun':    [(T7_ninsun, LYR['T7'], 'mp', 1)],
            'Lamuri':    [(T5_lamuri, None, 'mp', 1)],
            'Chorus':    [(T17_trio, LYR['T17'], 'mf', 1)],
            'Shamhat':   [(T12_shamhat, LYR['T12'], 'p', 1)],
        }
    }
    build_scene(sc17a, parts)

    # Sub-scene 17b: 62m, 5/8, ♩=72 — T15 battle memory + T20
    sc17b = {
        'n_measures': 62, 'ts_str': '5/8', 'ks_int': 2, 'bpm': 72,
        'label': 'Scene 17b: Memory of battle',
        'piano_chords': ['D2','F#2','A2','C#3'],
        'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4',
        'featured': {
            'Gilgamesh': [(T20_orch, LYR['T20'], 'ff', 1)],
            'Chorus':    [(T20_orch, LYR['T20'], 'fff', 1)],
            'Brass':     [(T20_orch, None, 'fff', 1)],
            'Winds':     [(T15_orch, None, 'ff', 1)],
            'Mkrimani':  [(T3_mkrimani, LYR['T3'], 'ff', 1)],
            'Mtavari':   [(T3_mtavari, LYR['T3'], 'ff', 1)],
            'Bani':      [(T3_bani, LYR['T3'], 'ff', 1)],
            'Enkidu':    [(T6_enkidu, LYR['enkidu_first'], 'pp', 1)],
        }
    }
    build_scene(sc17b, parts)

    # Sub-scene 17c: 61m, 4/4, ♩=88 — Final resolution T3 fff → quiet
    sc17c = {
        'n_measures': 61, 'ts_str': '4/4', 'ks_int': 2, 'bpm': 88,
        'label': 'Scene 17c: Resolution — Alilo',
        'piano_chords': ['D2','F#2','A2','D3'],
        'strings_pitches': ['D2','A2','D3'],
        'drone_pitch': 'D4',
        'featured': {
            'Mkrimani':  [(T3_mkrimani, LYR['T3'], 'fff', 1)],
            'Mtavari':   [(T3_mtavari, LYR['T3'], 'fff', 1)],
            'Bani':      [(T3_bani, LYR['T3'], 'fff', 1)],
            'Gilgamesh': [(T3_mkrimani, LYR['final_solo'], 'f', 1)],
            'Chorus':    [(T3_mkrimani, LYR['T3'], 'fff', 1)],
            'Shamhat':   [(T11_sop1, LYR['T11_s1'], 'ff', 1)],
            'Ninsun':    [(T11_alto, LYR['T11_al'], 'ff', 1)],
            'Brass':     [(T3_mkrimani, None, 'fff', 1)],
            'Lamuri':    [(T5_lamuri, None, 'ff', 1)],
        }
    }
    build_scene(sc17c, parts)

    # ══════════════════════════════════════════════════════════════════
    # Add all parts to score
    # ══════════════════════════════════════════════════════════════════

    part_order = [
        'Gilgamesh','Enkidu','Ninsun','Shamhat','Humbaba_Utnapishti',
        'Mkrimani','Mtavari','Bani','Chorus',
        'Lamuri','Chuniri','Panduri',
        'Strings','Winds','Brass','Cello','Piano'
    ]
    for pname in part_order:
        sc.insert(0, parts[pname])

    return sc

# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("Building ŠAMNU AZUZI v3 score...")
    print(f"Output: {OUT_FILE}")

    sc = build_score()

    # Count measures per part for verification
    part_names = [
        'Gilgamesh','Enkidu','Ninsun','Shamhat','Humbaba_Utnapishti',
        'Mkrimani','Mtavari','Bani','Chorus',
        'Lamuri','Chuniri','Panduri',
        'Strings','Winds','Brass','Cello','Piano'
    ]
    print("\nMeasure counts per part:")
    for pname in part_names:
        for p in sc.parts:
            if p.partName == pname:
                mc = len(p.getElementsByClass('Measure'))
                print(f"  {pname:25s}: {mc} measures")
                break

    # Scene totals
    act_totals = {
        'Act I':   80 + 82 + 76,   # = 238
        'Act II':  84 + 84 + 84 + 83,  # = 335
        'Act III': 82 + 82 + 81,   # = 245
        'Act IV':  92 + 91 + 91,   # = 274
        'Act V':   100 + 97 + 100 + 61 + 62 + 61,  # = 481
    }
    total = sum(act_totals.values())
    print(f"\nTarget measure totals per act:")
    for act, t in act_totals.items():
        print(f"  {act}: {t}")
    print(f"  TOTAL: {total}")

    print("\nWriting MusicXML...")
    sc.write('musicxml', fp=OUT_FILE)
    print(f"Done! Written to: {OUT_FILE}")
