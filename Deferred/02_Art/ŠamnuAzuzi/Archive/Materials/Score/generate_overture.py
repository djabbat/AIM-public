#!/usr/bin/env python3
"""
ŠAMNU AZUZI — OVERTURE
სამნუ ა-ზუ-ზი / Samnu A-zu-zi
Music: Dr. Jaba Tkemaladze

180 measures · ~9 minutes · 17 parts
Sections:
  1. Introduction "Uruk"          m.1–20    G minor   Largo ♩=50
  2. Exposition A "Gilgamesh"     m.21–50   D major   Allegro moderato ♩=72
  3. Exposition B "Enkidu/Nature" m.51–80   A minor   Andante pastorale ♩=66
  4. Development "Conflict"       m.81–120  chromatic Agitato ♩=88
  5. Recapitulation "Triumphant"  m.121–150 D major   Maestoso ♩=72
  6. Coda "Ninsun"                m.151–180 D minor→A Lento ♩=50
"""

import os
from music21 import (
    stream, note, chord, tempo, meter, key, dynamics,
    expressions, metadata, instrument, clef, bar, pitch
)

OUT_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "SAMNU_AZUZI_Overture.musicxml"
)

# ─────────────────────────────────────────────
# THEMES
# ─────────────────────────────────────────────

URUK_MOTIF   = [('G3',2),('F3',1),('Eb3',1),('D3',1),('C3',1),('Bb2',2),('G2',4)]   # 12 beats

T1_mkrimani  = [('D5',1),('F#5',0.5),('A5',0.5),('G5',1),('F#5',0.5),
                ('E5',0.5),('D5',1),('C#5',0.5),('D5',1.5)]   # 7 beats
T1_mtavari   = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),
                ('C#5',0.5),('D4',1),('B3',0.5),('A4',1.5)]   # 7 beats
T1_bani      = [('D3',1),('A3',0.5),('D4',0.5),('A3',1),('D3',0.5),
                ('A2',0.5),('D3',1),('A2',0.5),('D3',1.5)]    # 7 beats

T1_mtavari_chrom = [('A4',1),('D5',0.5),('F#5',0.5),('E5',1),('D5',0.5),
                    ('C4',0.5),('C#5',0.5),('D4',1),('B3',0.5),('A4',1.5)]  # chromatic variant

T4_lamuri    = [('D4',1.5),('R',0.5),('E4',1),('R',0.5),('G4',0.5),
                ('A4',1),('G4',0.5),('E4',1),('D4',1.5),('R',0.5),
                ('G4',1),('A4',0.5),('C5',0.5),('D5',1),('C5',0.5),
                ('A4',0.5),('G4',1.5),('R',0.5)]              # 14 beats

T7_ninsun    = [('D4',1),('F4',0.5),('E4',0.5),('D4',1),('C4',0.5),('D4',0.5),
                ('F4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',0.5),('E4',0.5),('D4',1)]  # 9 beats
T7_chuniri   = [('A3',2),('F3',1),('G3',1),('A3',1),('C4',1),('D4',2),('A3',2)]    # 10 beats

T19_chromatic = [('D4',0.5),('Db4',0.5),('C4',0.5),('B3',0.5),('Bb3',1),
                 ('A3',0.5),('Ab3',0.5),('G3',0.5),('F#3',0.5),('F3',1),
                 ('E3',0.5),('Eb3',0.5),('D3',2)]             # 9 beats

# ─────────────────────────────────────────────
# CORE HELPERS
# ─────────────────────────────────────────────

def make_element(p_str, dur_q):
    """Create a Note or Rest from pitch string and quarter duration."""
    if p_str == 'R':
        r = note.Rest()
        r.duration.quarterLength = dur_q
        return r
    n = note.Note(p_str)
    n.duration.quarterLength = dur_q
    return n


def whole_note(p_str, dyn_str=None):
    """Whole note (4 beats)."""
    n = make_element(p_str, 4.0)
    if dyn_str:
        n.dynamic = dynamics.Dynamic(dyn_str)
    return n


def whole_rest():
    r = note.Rest()
    r.duration.quarterLength = 4.0
    return r


def whole_chord(pitches, dyn_str=None):
    c = chord.Chord(pitches)
    c.duration.quarterLength = 4.0
    if dyn_str:
        c.dynamic = dynamics.Dynamic(dyn_str)
    return c


def set_dyn(elem, dyn_str):
    elem.dynamic = dynamics.Dynamic(dyn_str)
    return elem


def make_measure(measure_number, content_list, add_key=None, add_time=None, add_tempo=None, add_text=None):
    """
    Create a single Measure with measure_number and content.
    content_list: flat list of note/rest/chord objects that sum to 4 beats.
    """
    m = stream.Measure(number=measure_number)
    if add_key is not None:
        m.insert(0, key.KeySignature(add_key))
    if add_time is not None:
        m.insert(0, meter.TimeSignature(add_time))
    if add_tempo is not None:
        mm_mark, mm_text = add_tempo
        mm = tempo.MetronomeMark(number=mm_mark, referent='quarter')
        if mm_text:
            mm.text = mm_text
        m.insert(0, mm)
    if add_text is not None:
        te = expressions.TextExpression(add_text)
        te.positionVertical = 'above'
        m.insert(0, te)
    for elem in content_list:
        m.append(elem)
    return m


# ─────────────────────────────────────────────
# THEME → MEASURE SPLITTER
# ─────────────────────────────────────────────

def theme_to_flat_notes(seq):
    """Convert seq to list of (pitch_str, dur) cycling indefinitely generator."""
    flat = list(seq)
    i = 0
    while True:
        yield flat[i % len(flat)]
        i += 1


def seq_to_measures(seq, n_measures, beats=4.0):
    """
    Slice a (cycled) theme sequence into n_measures worth of measures.
    Returns list of lists-of-notes, each list sums to `beats`.
    """
    gen = theme_to_flat_notes(seq)
    result = []
    for _ in range(n_measures):
        bucket = []
        bucket_dur = 0.0
        leftover = None
        while abs(bucket_dur - beats) > 1e-9:
            remaining = beats - bucket_dur
            if leftover is not None:
                p, d = leftover
                leftover = None
            else:
                p, d = next(gen)
            if d <= remaining + 1e-9:
                actual = min(d, remaining)
                bucket.append(make_element(p, actual))
                bucket_dur += actual
            else:
                # split
                bucket.append(make_element(p, remaining))
                bucket_dur += remaining
                leftover = (p, d - remaining)
                # Need to put leftover back for next iteration —
                # use a closure trick: inject into generator
        # Leftover needs to be remembered for next measure
        # Rebuild gen to inject leftover at front
        if leftover is not None:
            orig_gen = gen
            def new_gen(lft, g):
                yield lft
                yield from g
            gen = new_gen(leftover, gen)
            leftover = None
        result.append(bucket)
    return result


def seq_to_measures_stateful(seq):
    """
    Returns a callable that you call with n_measures each time,
    advancing through the theme continuously (no restart between sections).
    """
    state = {'gen': theme_to_flat_notes(seq), 'leftover': None}

    def get_measures(n_measures, beats=4.0):
        result = []
        gen = state['gen']
        leftover = state['leftover']
        for _ in range(n_measures):
            bucket = []
            bucket_dur = 0.0
            while abs(bucket_dur - beats) > 1e-9:
                remaining = beats - bucket_dur
                if leftover is not None:
                    p, d = leftover
                    leftover = None
                else:
                    p, d = next(gen)
                actual = min(d, remaining)
                bucket.append(make_element(p, actual))
                bucket_dur += actual
                if d > remaining + 1e-9:
                    leftover = (p, d - remaining)
            result.append(bucket)
        state['leftover'] = leftover
        return result

    return get_measures


# ─────────────────────────────────────────────
# PART BUILDER HELPER
# ─────────────────────────────────────────────

def new_part(inst_obj, part_name):
    p = stream.Part()
    p.id = part_name
    p.partName = part_name
    inst_obj.partName = part_name
    p.insert(0, inst_obj)
    return p


# ─────────────────────────────────────────────
# MAIN SCORE BUILDER
# ─────────────────────────────────────────────

def build_score():
    sc = stream.Score()
    md = metadata.Metadata()
    md.title = 'ŠAMNU AZUZI — Overture'
    md.composer = 'Dr. Jaba Tkemaladze'
    sc.insert(0, md)

    # All 180 measures per part will be stored as lists first, then assembled
    TOTAL = 180

    # Parts dict: name → Part object
    parts = {}
    inst_map = {
        'Flute':           instrument.Flute(),
        'Oboe':            instrument.Oboe(),
        'Clarinet':        instrument.Clarinet(),
        'Bassoon':         instrument.Bassoon(),
        'Horn':            instrument.Horn(),
        'Trumpet':         instrument.Trumpet(),
        'Trombone':        instrument.Trombone(),
        'Tuba':            instrument.Tuba(),
        'Timpani':         instrument.Timpani(),
        'Harp':            instrument.Piano(),
        'Violin_I':        instrument.Violin(),
        'Violin_II':       instrument.Violin(),
        'Viola':           instrument.Viola(),
        'Cello':           instrument.Violoncello(),
        'Contrabass':      instrument.Contrabass(),
        'Soprano':         instrument.Soprano(),
        'Percussion':      instrument.Percussion(),
    }
    names = list(inst_map.keys())
    for nm in names:
        parts[nm] = new_part(inst_map[nm], nm)

    # measure_data[part_name][measure_idx 0-based] = Measure object
    # We build all measures 1..180 for each part
    mdata = {nm: [None]*TOTAL for nm in names}

    # ── Section keys / time sigs ─────────────────────────────────────
    # Section boundaries (0-based measure indices):
    # S1:  0–19    G minor  -2  Largo 50
    # S2: 20–49    D major  +2  Allegro mod 72
    # S3: 50–79    A minor   0  Andante pastorale 66
    # S4: 80–119   (no key change, chromatic)  Agitato 88
    # S5: 120–149  D major  +2  Maestoso 72
    # S6: 150–179  D minor  -1  Lento 50

    KEY_AT   = {0: -2, 20: 2, 50: 0, 80: 0, 120: 2, 150: -1}
    TEMPO_AT = {0: (50, 'Largo'), 20: (72, 'Allegro moderato'), 50: (66, 'Andante pastorale'),
                80: (88, 'Agitato'), 120: (72, 'Maestoso'), 150: (50, 'Lento')}
    TEXT_AT  = {0: 'Uruk', 20: 'Gilgamesh', 50: 'Enkidu / Nature',
                80: 'Conflict — Development', 120: "Gilgamesh Triumphant — Recapitulation A'",
                150: 'Ninsun — Coda'}

    def get_section_attrs(mi, first_part=False):
        """Return (add_key, add_time, add_tempo, add_text) for measure index mi."""
        ak = KEY_AT.get(mi) if first_part else None
        at = '4/4' if mi == 0 and first_part else None
        atp = TEMPO_AT.get(mi) if first_part else None
        atx = TEXT_AT.get(mi) if first_part else None
        return ak, at, atp, atx

    # ─── build a helper to stamp key/tempo on first part of each section ───────
    def mk(part_name, mi, content):
        """Create measure for part at 0-based index mi with content list."""
        is_first = (part_name == 'Flute')
        ak = KEY_AT.get(mi) if is_first else None
        at_ts = '4/4' if (mi == 0 and is_first) else None
        atp = TEMPO_AT.get(mi) if is_first else None
        atx = TEXT_AT.get(mi) if is_first else None
        return make_measure(mi+1, content, add_key=ak, add_time=at_ts,
                            add_tempo=atp, add_text=atx)

    # ─────────────────────────────────────────────────────────────────
    # SECTION 1: m.1–20 (idx 0–19) — G minor, Largo ♩=50
    # ─────────────────────────────────────────────────────────────────

    for nm in names:
        for mi in range(20):
            # Build content per instrument
            if nm == 'Contrabass':
                content = [whole_note('G2', 'ppp' if mi == 0 else None)]
            elif nm == 'Cello':
                if mi < 5:
                    content = [whole_note('G2', 'ppp' if mi == 0 else None)]
                elif mi < 10:
                    # G2(1) D3(1.5) G3(1.5)
                    n1 = make_element('G2', 1.0)
                    if mi == 5: n1.dynamic = dynamics.Dynamic('p')
                    n2 = make_element('D3', 1.5)
                    n3 = make_element('G3', 1.5)
                    content = [n1, n2, n3]
                else:
                    content = [whole_note('D3' if mi < 15 else 'G2',
                                         'mp' if mi == 10 else None)]
            elif nm == 'Bassoon':
                if mi < 5:
                    content = [whole_note('G2', 'ppp' if mi == 0 else None)]
                elif mi < 10:
                    n1 = make_element('G2', 1.0)
                    if mi == 5: n1.dynamic = dynamics.Dynamic('p')
                    content = [n1, make_element('D3', 1.5), make_element('G3', 1.5)]
                else:
                    content = [whole_note('G2', 'p' if mi == 15 else None)]
            elif nm == 'Horn':
                if mi < 10:
                    content = [whole_note('G2', 'ppp' if mi == 0 else None)]
                elif mi < 15:
                    c = chord.Chord(['G2', 'Bb2', 'D3'])
                    c.duration.quarterLength = 4.0
                    if mi == 10: c.dynamic = dynamics.Dynamic('mp')
                    content = [c]
                else:
                    c = chord.Chord(['G2', 'Bb2', 'D3'])
                    c.duration.quarterLength = 4.0
                    content = [c]
            elif nm == 'Percussion':
                if mi < 15:
                    content = [whole_rest()]
                elif mi == 15:
                    tam = make_element('C4', 1.0)
                    tam.dynamic = dynamics.Dynamic('ff')
                    tam.expressions.append(expressions.TextExpression('TAM-TAM'))
                    rest3 = note.Rest(); rest3.duration.quarterLength = 3.0
                    content = [tam, rest3]
                else:
                    content = [whole_rest()]
            elif nm == 'Flute':
                content = [whole_note('G4', 'ppp' if mi == 0 else None)]
            elif nm == 'Oboe':
                content = [whole_note('D4', 'ppp' if mi == 0 else None)]
            elif nm == 'Clarinet':
                content = [whole_note('G4', 'ppp' if mi == 0 else None)]
            elif nm == 'Trumpet':
                content = [whole_rest()]
            elif nm == 'Trombone':
                content = [whole_note('G2', 'ppp' if mi == 0 else None)]
            elif nm == 'Tuba':
                content = [whole_note('G1', 'ppp' if mi == 0 else None)]
            elif nm == 'Timpani':
                content = [whole_note('G2', 'ppp' if mi == 0 else None)]
            elif nm == 'Harp':
                c = chord.Chord(['G2', 'D3', 'G3', 'Bb3'])
                c.duration.quarterLength = 4.0
                if mi == 0: c.dynamic = dynamics.Dynamic('ppp')
                content = [c]
            elif nm == 'Violin_I':
                n = whole_note('G4', 'ppp' if mi == 0 else None)
                if mi == 15: n.dynamic = dynamics.Dynamic('ff')
                if mi == 16: n.dynamic = dynamics.Dynamic('p')
                content = [n]
            elif nm == 'Violin_II':
                content = [whole_note('D4', 'ppp' if mi == 0 else None)]
            elif nm == 'Viola':
                content = [whole_note('Bb3', 'ppp' if mi == 0 else None)]
            elif nm == 'Soprano':
                content = [whole_rest()]
            else:
                content = [whole_rest()]

            mdata[nm][mi] = mk(nm, mi, content)

    # ─────────────────────────────────────────────────────────────────
    # SECTION 2: m.21–50 (idx 20–49) — D major, Allegro ♩=72
    # ─────────────────────────────────────────────────────────────────

    # Pre-build theme measure sequences
    mk_gen   = seq_to_measures_stateful(T1_mkrimani)
    mt_gen   = seq_to_measures_stateful(T1_mtavari)
    bn_gen   = seq_to_measures_stateful(T1_bani)
    mk_gen2  = seq_to_measures_stateful(T1_mkrimani)
    mt_gen2  = seq_to_measures_stateful(T1_mtavari)
    mt_gen3  = seq_to_measures_stateful(T1_mtavari)
    bn_gen2  = seq_to_measures_stateful(T1_bani)
    bn_gen3  = seq_to_measures_stateful(T1_bani)
    bn_gen4  = seq_to_measures_stateful(T1_bani)

    # Pre-generate 30 measures each
    FL_S2   = seq_to_measures(T1_mkrimani, 30)
    OB_S2   = seq_to_measures(T1_mtavari, 30)
    CL_S2   = seq_to_measures(T1_mtavari, 30)
    BN_S2   = seq_to_measures(T1_bani, 30)
    VN1_S2  = seq_to_measures(T1_mkrimani, 30)
    VN2_S2  = seq_to_measures(T1_mtavari, 30)
    VA_S2   = seq_to_measures(T1_bani, 30)
    VC_S2   = seq_to_measures(T1_bani, 30)
    HN_S2   = seq_to_measures(T1_mtavari, 20)  # m.31–50
    TPT_S2a = seq_to_measures(T1_mtavari, 10)  # m.31–40
    TPT_S2b = seq_to_measures(T1_mtavari, 10)  # m.41–50

    for nm in names:
        for li in range(30):
            mi = 20 + li

            # Key sig at section start (first part only)
            is_key = (mi == 20)
            ak = KEY_AT[20] if is_key else None
            atp = TEMPO_AT[20] if is_key and nm == 'Flute' else None
            atx = TEXT_AT[20] if is_key and nm == 'Flute' else None

            if nm == 'Flute':
                content = FL_S2[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Oboe':
                content = OB_S2[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Clarinet':
                content = CL_S2[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Bassoon':
                content = BN_S2[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Horn':
                if li < 10:
                    content = [whole_note('A3', 'mf' if li == 0 else None)]
                else:
                    content = HN_S2[li - 10]
                    if li == 10: content[0].dynamic = dynamics.Dynamic('f')
            elif nm == 'Trumpet':
                if li < 10:
                    content = [whole_rest()]
                elif li < 20:
                    content = TPT_S2a[li - 10]
                    if li == 10: content[0].dynamic = dynamics.Dynamic('f')
                else:
                    content = TPT_S2b[li - 20]
                    if li == 20: content[0].dynamic = dynamics.Dynamic('fff')
            elif nm == 'Trombone':
                dyn = 'mf' if li == 0 else ('f' if li == 10 else ('ff' if li == 20 else None))
                content = [whole_note('D2', dyn)]
            elif nm == 'Tuba':
                dyn = 'mf' if li == 0 else ('ff' if li == 20 else None)
                content = [whole_note('D1', dyn)]
            elif nm == 'Timpani':
                n = whole_note('D2' if li % 2 == 0 else 'A2',
                               'mf' if li == 0 else ('fff' if li == 20 else None))
                content = [n]
            elif nm == 'Harp':
                if li < 10:
                    c = whole_chord(['D3', 'F#3', 'A3', 'D4'], 'mf' if li == 0 else None)
                elif li < 20:
                    c = whole_chord(['D3', 'F#3', 'A3', 'D4'], 'f' if li == 10 else None)
                else:
                    c = whole_chord(['D3', 'A3', 'D4', 'F#4'], 'ff' if li == 20 else None)
                content = [c]
            elif nm == 'Violin_I':
                content = VN1_S2[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
                if li == 10: content[0].dynamic = dynamics.Dynamic('f')
                if li == 20: content[0].dynamic = dynamics.Dynamic('fff')
            elif nm == 'Violin_II':
                content = VN2_S2[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
                if li == 10: content[0].dynamic = dynamics.Dynamic('f')
                if li == 20: content[0].dynamic = dynamics.Dynamic('fff')
            elif nm == 'Viola':
                content = VA_S2[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
                if li == 10: content[0].dynamic = dynamics.Dynamic('f')
                if li == 20: content[0].dynamic = dynamics.Dynamic('fff')
            elif nm == 'Cello':
                content = VC_S2[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Contrabass':
                dyn = 'mf' if li == 0 else ('fff' if li == 20 else None)
                content = [whole_note('D2', dyn)]
            elif nm == 'Soprano':
                content = [whole_rest()]
            elif nm == 'Percussion':
                content = [whole_rest()]
            else:
                content = [whole_rest()]

            m = make_measure(mi+1, content,
                             add_key=ak if nm == 'Flute' or ak is not None else None,
                             add_tempo=atp, add_text=atx)
            # For non-flute parts, also add key sig at section start
            if is_key and nm != 'Flute':
                m.insert(0, key.KeySignature(KEY_AT[20]))
            mdata[nm][mi] = m

    # ─────────────────────────────────────────────────────────────────
    # SECTION 3: m.51–80 (idx 50–79) — A minor, Andante pastorale ♩=66
    # ─────────────────────────────────────────────────────────────────

    FL_S3   = seq_to_measures(T4_lamuri, 10)    # m.51–60 flute solo
    OB_S3   = seq_to_measures(T4_lamuri, 10)    # m.61–70 oboe echo
    CL_S3   = seq_to_measures(T4_lamuri, 10)    # m.61–70 clarinet echo
    VN1_S3  = seq_to_measures(T4_lamuri, 10)    # m.71–80 vn1
    VA_S3   = seq_to_measures(T4_lamuri, 10)    # m.71–80 viola
    VC_S3   = seq_to_measures(T4_lamuri, 10)    # m.71–80 cello

    for nm in names:
        for li in range(30):
            mi = 50 + li
            is_key = (mi == 50)
            ak = KEY_AT[50] if is_key else None
            atp = TEMPO_AT[50] if is_key and nm == 'Flute' else None
            atx = TEXT_AT[50] if is_key and nm == 'Flute' else None

            if nm == 'Flute':
                if li < 10:
                    content = FL_S3[li]
                    if li == 0: content[0].dynamic = dynamics.Dynamic('pp')
                else:
                    content = [whole_note('A4', 'mp' if li == 10 else None)]
            elif nm == 'Oboe':
                if li < 10:
                    content = [whole_note('D4', 'pp' if li == 0 else None)]
                elif li < 20:
                    content = OB_S3[li - 10]
                    if li == 10: content[0].dynamic = dynamics.Dynamic('p')
                else:
                    content = [whole_note('D4', 'mp' if li == 20 else None)]
            elif nm == 'Clarinet':
                if li < 10:
                    content = [whole_note('E4', 'pp' if li == 0 else None)]
                elif li < 20:
                    content = CL_S3[li - 10]
                    if li == 10: content[0].dynamic = dynamics.Dynamic('p')
                else:
                    content = [whole_note('E4', 'mp' if li == 20 else None)]
            elif nm == 'Bassoon':
                content = [whole_note('A2', 'pp' if li == 0 else None)]
            elif nm == 'Horn':
                c = whole_chord(['A2', 'C3', 'E3'], 'pp' if li == 0 else None)
                content = [c]
            elif nm == 'Trumpet':
                content = [whole_rest()]
            elif nm == 'Trombone':
                content = [whole_note('A1', 'pp' if li == 0 else None)]
            elif nm == 'Tuba':
                content = [whole_note('A1', 'pp' if li == 0 else None)]
            elif nm == 'Timpani':
                content = [whole_note('A2', 'pp' if li == 0 else None)]
            elif nm == 'Harp':
                c = whole_chord(['A2', 'E3', 'A3', 'C4'], 'pp' if li == 0 else None)
                content = [c]
            elif nm == 'Violin_I':
                if li < 10:
                    content = [whole_note('A5', 'pp' if li == 0 else None)]
                elif li < 20:
                    content = [whole_note('E5', 'mp' if li == 10 else None)]
                else:
                    content = VN1_S3[li - 20]
                    if li == 20: content[0].dynamic = dynamics.Dynamic('mp')
            elif nm == 'Violin_II':
                if li < 20:
                    content = [whole_note('E4', 'pp' if li == 0 else None)]
                else:
                    content = [whole_note('A4', 'mp' if li == 20 else None)]
            elif nm == 'Viola':
                if li < 20:
                    content = [whole_note('C4', 'pp' if li == 0 else None)]
                else:
                    content = VA_S3[li - 20]
                    if li == 20: content[0].dynamic = dynamics.Dynamic('mp')
            elif nm == 'Cello':
                if li < 20:
                    content = [whole_note('A3', 'pp' if li == 0 else None)]
                else:
                    content = VC_S3[li - 20]
                    if li == 20: content[0].dynamic = dynamics.Dynamic('mp')
            elif nm == 'Contrabass':
                content = [whole_note('A2', 'pp' if li == 0 else None)]
            elif nm == 'Soprano':
                content = [whole_rest()]
            elif nm == 'Percussion':
                content = [whole_rest()]
            else:
                content = [whole_rest()]

            m = make_measure(mi+1, content,
                             add_key=ak if nm == 'Flute' else None,
                             add_tempo=atp, add_text=atx)
            if is_key and nm != 'Flute':
                m.insert(0, key.KeySignature(KEY_AT[50]))
            mdata[nm][mi] = m

    # ─────────────────────────────────────────────────────────────────
    # SECTION 4: m.81–120 (idx 80–119) — Agitato ♩=88, chromatic dev
    # ─────────────────────────────────────────────────────────────────

    FL_S4a  = seq_to_measures(T4_lamuri,  10)   # m.81–90
    FL_S4b  = seq_to_measures(T4_lamuri,  10)   # m.111–120
    OB_S4   = seq_to_measures(T1_mtavari, 40)
    CL_S4   = seq_to_measures(T4_lamuri,  40)
    BN_S4a  = seq_to_measures(T19_chromatic, 10) # m.91–100
    BN_S4b  = seq_to_measures(T19_chromatic, 10) # m.101–110
    HN_S4a  = seq_to_measures(T1_mtavari, 10)   # m.81–90
    TPT_S4a = seq_to_measures(T1_mtavari, 10)   # m.81–90
    VN1_S4a = seq_to_measures(T1_mkrimani, 10)  # m.81–90
    VN2_S4  = seq_to_measures(T4_lamuri,  40)
    VA_S4   = seq_to_measures(T4_lamuri,  40)
    VC_S4   = seq_to_measures(T1_bani,    40)

    for nm in names:
        for li in range(40):
            mi = 80 + li
            is_key = (mi == 80)
            atp = TEMPO_AT[80] if is_key and nm == 'Flute' else None
            atx = TEXT_AT[80] if is_key and nm == 'Flute' else None
            ak  = KEY_AT[80]  if is_key else None

            if nm == 'Flute':
                if li < 10:
                    content = FL_S4a[li]
                    if li == 0: content[0].dynamic = dynamics.Dynamic('f')
                elif li < 20:
                    content = [whole_note('D5', 'mf' if li == 10 else None)]
                elif li < 30:
                    content = [whole_note('D5', 'ff' if li == 20 else None)]
                else:
                    content = FL_S4b[li - 30]
                    if li == 30: content[0].dynamic = dynamics.Dynamic('p')
            elif nm == 'Oboe':
                content = OB_S4[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('f')
            elif nm == 'Clarinet':
                content = CL_S4[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('f')
            elif nm == 'Bassoon':
                if li < 10:
                    content = [whole_note('G2', 'f' if li == 0 else None)]
                elif li < 20:
                    content = BN_S4a[li - 10]
                    if li == 10: content[0].dynamic = dynamics.Dynamic('mf')
                elif li < 30:
                    content = BN_S4b[li - 20]
                    if li == 20: content[0].dynamic = dynamics.Dynamic('ff')
                else:
                    content = [whole_note('D3', 'mf' if li == 30 else None)]
            elif nm == 'Horn':
                if li < 10:
                    content = HN_S4a[li]
                    if li == 0: content[0].dynamic = dynamics.Dynamic('f')
                else:
                    c = whole_chord(['A2', 'D3', 'G3'], 'ff' if li == 10 else None)
                    content = [c]
            elif nm == 'Trumpet':
                if li < 10:
                    content = TPT_S4a[li]
                    if li == 0: content[0].dynamic = dynamics.Dynamic('f')
                else:
                    content = [whole_note('A4', 'ff' if li == 10 else None)]
            elif nm == 'Trombone':
                content = [whole_note('D2', 'ff' if li == 0 else None)]
            elif nm == 'Tuba':
                content = [whole_note('D1', 'ff' if li == 0 else None)]
            elif nm == 'Timpani':
                content = [whole_note('D2', 'ff' if li == 0 else None)]
            elif nm == 'Harp':
                c = whole_chord(['D3', 'F3', 'A3', 'C4'], 'ff' if li == 0 else None)
                content = [c]
            elif nm == 'Violin_I':
                if li < 10:
                    content = VN1_S4a[li]
                    if li == 0: content[0].dynamic = dynamics.Dynamic('f')
                else:
                    content = [whole_note('A5', 'ff' if li == 10 else None)]
            elif nm == 'Violin_II':
                content = VN2_S4[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('f')
            elif nm == 'Viola':
                content = VA_S4[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('f')
            elif nm == 'Cello':
                content = VC_S4[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('f')
            elif nm == 'Contrabass':
                content = [whole_note('D2', 'ff' if li == 0 else None)]
            elif nm == 'Soprano':
                content = [whole_rest()]
            elif nm == 'Percussion':
                if li % 4 == 0:
                    n = make_element('C4', 1.0)
                    n.dynamic = dynamics.Dynamic('ff')
                    rest3 = note.Rest(); rest3.duration.quarterLength = 3.0
                    content = [n, rest3]
                else:
                    content = [whole_rest()]
            else:
                content = [whole_rest()]

            m = make_measure(mi+1, content,
                             add_key=ak if nm == 'Flute' else None,
                             add_tempo=atp, add_text=atx)
            if is_key and nm != 'Flute':
                m.insert(0, key.KeySignature(KEY_AT[80]))
            mdata[nm][mi] = m

    # ─────────────────────────────────────────────────────────────────
    # SECTION 5: m.121–150 (idx 120–149) — D major, Maestoso ♩=72
    # ─────────────────────────────────────────────────────────────────

    FL_S5   = seq_to_measures(T1_mkrimani,       30)
    OB_S5   = seq_to_measures(T1_mtavari_chrom,  30)
    CL_S5   = seq_to_measures(T1_mtavari_chrom,  30)
    BN_S5   = seq_to_measures(T1_bani,           30)
    HN_S5a  = seq_to_measures(T1_mtavari,        10)
    TPT_S5  = seq_to_measures(T1_mtavari,        20)
    VN1_S5  = seq_to_measures(T1_mkrimani,       30)
    VN2_S5  = seq_to_measures(T1_mtavari_chrom,  30)
    VA_S5   = seq_to_measures(T1_bani,           30)
    VC_S5   = seq_to_measures(T1_bani,           20)

    for nm in names:
        for li in range(30):
            mi = 120 + li
            is_key = (mi == 120)
            ak  = KEY_AT[120] if is_key else None
            atp = TEMPO_AT[120] if is_key and nm == 'Flute' else None
            atx = TEXT_AT[120] if is_key and nm == 'Flute' else None

            if nm == 'Flute':
                content = FL_S5[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Oboe':
                content = OB_S5[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Clarinet':
                content = CL_S5[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Bassoon':
                content = BN_S5[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
            elif nm == 'Horn':
                if li < 10:
                    content = HN_S5a[li]
                    if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
                else:
                    c = whole_chord(['D3', 'A3', 'D4'], 'ff' if li == 10 else None)
                    content = [c]
            elif nm == 'Trumpet':
                if li < 10:
                    content = [whole_note('A4', 'mf' if li == 0 else None)]
                else:
                    content = TPT_S5[li - 10]
                    if li == 10: content[0].dynamic = dynamics.Dynamic('ff')
            elif nm == 'Trombone':
                if li < 10:
                    content = [whole_note('D2', 'mf' if li == 0 else None)]
                elif li < 20:
                    content = [whole_note('D2', 'ff' if li == 10 else None)]
                else:
                    content = [whole_note('D2', 'p' if li == 20 else None)]
            elif nm == 'Tuba':
                if li < 10:
                    content = [whole_note('D1', 'mf' if li == 0 else None)]
                elif li < 20:
                    content = [whole_note('D1', 'ff' if li == 10 else None)]
                else:
                    content = [whole_note('D1', 'p' if li == 20 else None)]
            elif nm == 'Timpani':
                if li < 10:
                    content = [whole_note('D2', 'mf' if li == 0 else None)]
                elif li < 20:
                    content = [whole_note('A2', 'ff' if li == 10 else None)]
                else:
                    content = [whole_note('D2', 'p' if li == 20 else None)]
            elif nm == 'Harp':
                if li < 20:
                    c = whole_chord(['D3', 'F#3', 'A3', 'D4'], 'f' if li == 0 else None)
                else:
                    c = whole_chord(['D3', 'F3', 'A3', 'D4'], 'p' if li == 20 else None)
                content = [c]
            elif nm == 'Violin_I':
                content = VN1_S5[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
                if li == 10: content[0].dynamic = dynamics.Dynamic('ff')
                if li == 20: content[0].dynamic = dynamics.Dynamic('p')
            elif nm == 'Violin_II':
                content = VN2_S5[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
                if li == 10: content[0].dynamic = dynamics.Dynamic('ff')
                if li == 20: content[0].dynamic = dynamics.Dynamic('p')
            elif nm == 'Viola':
                content = VA_S5[li]
                if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
                if li == 10: content[0].dynamic = dynamics.Dynamic('ff')
                if li == 20: content[0].dynamic = dynamics.Dynamic('p')
            elif nm == 'Cello':
                if li < 20:
                    content = VC_S5[li]
                    if li == 0: content[0].dynamic = dynamics.Dynamic('mf')
                else:
                    content = [whole_note('D3', 'p' if li == 20 else None)]
            elif nm == 'Contrabass':
                if li < 20:
                    content = [whole_note('D2', 'mf' if li == 0 else None)]
                else:
                    content = [whole_note('D2', 'p' if li == 20 else None)]
            elif nm == 'Soprano':
                content = [whole_rest()]
            elif nm == 'Percussion':
                if 10 <= li < 20:
                    n = make_element('C4', 1.0)
                    n.dynamic = dynamics.Dynamic('ff')
                    rest3 = note.Rest(); rest3.duration.quarterLength = 3.0
                    content = [n, rest3]
                else:
                    content = [whole_rest()]
            else:
                content = [whole_rest()]

            m = make_measure(mi+1, content,
                             add_key=ak if nm == 'Flute' else None,
                             add_tempo=atp, add_text=atx)
            if is_key and nm != 'Flute':
                m.insert(0, key.KeySignature(KEY_AT[120]))
            mdata[nm][mi] = m

    # ─────────────────────────────────────────────────────────────────
    # SECTION 6: m.151–180 (idx 150–179) — D minor→A, Lento ♩=50
    # ─────────────────────────────────────────────────────────────────

    VN1_S6a  = seq_to_measures(T7_chuniri, 10)   # m.151–160
    OB_S6    = seq_to_measures(T7_ninsun,  10)   # m.161–170

    for nm in names:
        for li in range(30):
            mi = 150 + li
            is_key = (mi == 150)
            ak  = KEY_AT[150] if is_key else None
            atp = TEMPO_AT[150] if is_key and nm == 'Flute' else None
            atx = TEXT_AT[150] if is_key and nm == 'Flute' else None

            if nm == 'Violin_I':
                if li < 10:
                    content = VN1_S6a[li]
                    if li == 0: content[0].dynamic = dynamics.Dynamic('pp')
                elif li < 20:
                    content = [whole_note('D5', 'ppp' if li == 10 else None)]
                else:
                    content = [whole_note('A4', 'pppp' if li == 20 else None)]
            elif nm == 'Violin_II':
                if li < 10:
                    content = [whole_note('A4', 'pp' if li == 0 else None)]
                elif li < 20:
                    content = [whole_note('F4', 'ppp' if li == 10 else None)]
                else:
                    content = [whole_note('A4', 'pppp' if li == 20 else None)]
            elif nm == 'Viola':
                if li < 10:
                    content = [whole_note('D4', 'pp' if li == 0 else None)]
                elif li < 20:
                    content = [whole_note('D4', 'ppp' if li == 10 else None)]
                else:
                    content = [whole_note('A3', 'pppp' if li == 20 else None)]
            elif nm == 'Cello':
                if li < 20:
                    content = [whole_note('A3', 'pp' if li == 0 else None)]
                else:
                    content = [whole_note('A3', 'pppp' if li == 20 else None)]
            elif nm == 'Contrabass':
                if li < 20:
                    content = [whole_note('A2', 'pp' if li == 0 else None)]
                else:
                    content = [whole_note('A2', 'pppp' if li == 20 else None)]
            elif nm == 'Oboe':
                if li < 10:
                    content = [whole_note('D4', 'pp' if li == 0 else None)]
                elif li < 20:
                    content = OB_S6[li - 10]
                    if li == 10: content[0].dynamic = dynamics.Dynamic('ppp')
                else:
                    content = [whole_note('A3', 'pppp' if li == 20 else None)]
            elif nm == 'Flute':
                content = [whole_note('A5',
                                      'pp' if li == 0 else ('pppp' if li == 20 else None))]
            elif nm == 'Clarinet':
                content = [whole_note('E4',
                                      'pp' if li == 0 else ('pppp' if li == 20 else None))]
            elif nm == 'Bassoon':
                content = [whole_note('D3',
                                      'pp' if li == 0 else ('pppp' if li == 20 else None))]
            elif nm == 'Horn':
                c = whole_chord(['A2', 'E3'],
                                'pp' if li == 0 else ('pppp' if li == 20 else None))
                content = [c]
            elif nm == 'Trumpet':
                content = [whole_rest()]
            elif nm == 'Trombone':
                content = [whole_note('A1',
                                      'pp' if li == 0 else ('pppp' if li == 20 else None))]
            elif nm == 'Tuba':
                content = [whole_note('A1',
                                      'pp' if li == 0 else ('pppp' if li == 20 else None))]
            elif nm == 'Timpani':
                content = [whole_note('A2',
                                      'pp' if li == 0 else ('pppp' if li == 20 else None))]
            elif nm == 'Harp':
                if li < 20:
                    c = whole_chord(['D3', 'F3', 'A3', 'D4'], 'pp' if li == 0 else None)
                else:
                    c = whole_chord(['A2', 'E3', 'A3'], 'pppp' if li == 20 else None)
                content = [c]
            elif nm == 'Soprano':
                if li < 10:
                    content = [whole_rest()]
                else:
                    content = [whole_note('A4',
                                         'ppp' if li == 10 else ('pppp' if li == 20 else None))]
            elif nm == 'Percussion':
                content = [whole_rest()]
            else:
                content = [whole_rest()]

            m = make_measure(mi+1, content,
                             add_key=ak if nm == 'Flute' else None,
                             add_tempo=atp, add_text=atx)
            if is_key and nm != 'Flute':
                m.insert(0, key.KeySignature(KEY_AT[150]))
            mdata[nm][mi] = m

    # ─────────────────────────────────────────────────────────────────
    # ASSEMBLE: add all measures to parts, then add parts to score
    # ─────────────────────────────────────────────────────────────────

    # Verify all measures are filled
    EXPECTED = 180
    ok = True
    for nm in names:
        missing = [i for i in range(EXPECTED) if mdata[nm][i] is None]
        if missing:
            print(f"ERROR: {nm} missing measures at indices: {missing}")
            ok = False
    if not ok:
        raise RuntimeError("Some measures are missing — aborting.")

    for nm in names:
        p = parts[nm]
        for mi in range(EXPECTED):
            p.append(mdata[nm][mi])
        sc.append(p)

    # Validate total quarter-length
    print("Validating measure counts …")
    EXPECTED_QL = 180 * 4.0
    for nm in names:
        p = parts[nm]
        measures = list(p.getElementsByClass('Measure'))
        count = len(measures)
        total_ql = sum(
            sum(e.duration.quarterLength for e in m.notesAndRests)
            for m in measures
        )
        if count != 180 or abs(total_ql - EXPECTED_QL) > 0.5:
            print(f"  WARNING {nm}: {count} measures, {total_ql} beats (expected 180 / {EXPECTED_QL})")
        else:
            print(f"  OK {nm}: 180 measures, {total_ql:.1f} beats")

    return sc


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

if __name__ == '__main__':
    print("Building ŠAMNU AZUZI — Overture …")
    sc = build_score()
    print(f"Writing to: {OUT_FILE}")
    sc.write('musicxml', OUT_FILE)
    size = os.path.getsize(OUT_FILE)
    print(f"Done: {OUT_FILE}")
    print(f"File size: {size:,} bytes ({size / 1024:.1f} KB)")
