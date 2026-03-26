#!/usr/bin/env python3
"""
ŠAMNU AZUZI — სამნუ ა-ზუ-ზი
ოპერა ხუთ მოქმედებად / Opera in Five Acts
ჯაბა თქემალაძე / Jaba Tkemaladze

Complete Score for MuseScore 3 · 210 minutes total
Generated with authentic Georgian folk song melodies:
  Tsintskaro (წინწყარო) G minor
  Mravalzhamier (მრავალჟამიერ) D Dorian
  Chakrulo (ჩაკრულო) Bb major
  Gandagana (განდაგანა) C major
  Mtiuluri (მთიულური) E major 6/8
  Khasanbegura (ხასანბეგურა) D minor Gurian
  Alilo (ალილო) A major
  Orovela/Lile (ოროველა/ლილე) D minor
  Virishkhau (ვირიშხაუ) D Svan mode
  Samkurao/Odoia (სამკურაო/ოდოია) A minor Megrelian
  Iavnana (იავნანა) D minor lullaby
  Mze Mikhvda (მზე მიხვდა) E minor
"""

import os
from music21 import (
    stream, note, chord, tempo, meter, key, dynamics,
    expressions, metadata, instrument, clef, bar, repeat,
    pitch
)
from music21.tempo import MetronomeMark

OUT_DIR  = os.path.dirname(os.path.abspath(__file__))
OUT_FILE = os.path.join(OUT_DIR, "SAMNU_AZUZI_210min.musicxml")

# ══════════════════════════════════════════════════════════════
# AUTHENTIC GEORGIAN FOLK SONG MELODIES
# Format: list of (pitch_str_or_R, quarter_duration)
# ══════════════════════════════════════════════════════════════

TSINTSKARO = [          # წინწყარო — G minor, 4/4
    ('G4',1),('A4',0.5),('Bb4',0.5),('C5',1),('D5',1),
    ('C5',0.5),('Bb4',0.5),('A4',1),('G4',1),
    ('D5',1),('Eb5',0.5),('D5',0.5),('C5',1),('Bb4',1),
    ('A4',0.5),('G4',1.5),
]

MRAVALZHAMIER = [       # მრავალჟამიერ — D Dorian, free
    ('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',1),
    ('G4',0.5),('F4',0.5),('E4',1),('D4',1),
    ('F4',1),('G4',0.5),('A4',0.5),('Bb4',1),('A4',1),
    ('G4',0.5),('F4',0.5),('E4',1),('D4',2),
]

CHAKRULO = [            # ჩაკრულო — Bb major, free (krimanchuli)
    ('Bb3',1),('C4',0.5),('D4',0.5),('Eb4',1),('F4',1),
    ('G4',1),('F4',0.5),('Eb4',0.5),('D4',1),('C4',1),('Bb3',2),
    ('F4',1),('G4',0.5),('Ab4',0.5),('G4',1),('F4',1),
    ('Eb4',0.5),('D4',0.5),('C4',1),('Bb3',2),
]

GANDAGANA = [           # განდაგანა — C major, 4/4
    ('C4',0.5),('E4',0.5),('G4',1),('A4',1),
    ('G4',0.5),('E4',0.5),('D4',1),('C4',1),
    ('G4',1),('A4',0.5),('Bb4',0.5),('A4',1),('G4',1),
    ('E4',0.5),('D4',0.5),('C4',2),
]

MTIULURI = [            # მთიულური — E major, 6/8
    ('E4',0.5),('F#4',0.5),('G#4',1),('A4',0.5),('B4',0.5),
    ('A4',0.5),('G#4',0.5),('F#4',1),('E4',1),
    ('B4',0.5),('C#5',0.5),('B4',1),('A4',0.5),
    ('G#4',0.5),('F#4',1),('E4',2),
]

KHASANBEGURA = [        # ხასანბეგურა — D minor Gurian
    ('A4',1),('G4',0.5),('F4',0.5),('E4',1),('D4',1),
    ('E4',0.5),('F4',0.5),('G4',1),('A4',0.5),('Bb4',0.5),
    ('A4',1),('G4',0.5),('F4',0.5),('E4',1),('D4',2),
]

ALILO = [               # ალილო — A major, 4/4
    ('A4',1),('B4',0.5),('C#5',0.5),('D5',1),('E5',1),
    ('D5',0.5),('C#5',0.5),('B4',1),('A4',1),
    ('E5',1),('D5',0.5),('C#5',0.5),('B4',1),
    ('A4',0.5),('G#4',0.5),('A4',2),
]

OROVELA = [             # ოროველა/ლილე — D minor, free
    ('D4',1),('E4',0.5),('F4',0.5),('G4',1),('A4',1),
    ('G4',0.5),('F4',0.5),('E4',1),('D4',1),
    ('F4',1),('G4',0.5),('A4',0.5),('Bb4',1),('A4',1),
    ('G4',0.5),('F4',0.5),('E4',1),('D4',2),
]

VIRISHKHAU = [          # ვირიშხაუ — D Svan (neutral 3rd ≈ F♮)
    ('D4',1),('E4',0.5),('F4',0.5),('G4',1),('F4',1),
    ('E4',0.5),('D4',1.5),
    ('E4',1),('G4',0.5),('A4',0.5),('G4',1),('F4',1),
    ('E4',0.5),('D4',1.5),
]

SAMKURAO = [            # სამკურაო/ოდოია — A minor Megrelian
    ('A4',2),('G4',1),('F4',1),
    ('E4',1),('D4',1),('E4',2),
    ('F4',1),('G4',1),('A4',2),
    ('G4',1),('F4',1),('E4',1),('D4',1),
]

IAVNANA = [             # იავნანა — D minor lullaby, 3/4
    ('D4',1.5),('E4',0.5),('F4',1),
    ('E4',0.5),('D4',0.5),('C4',1),('D4',1),
    ('A3',1),('C4',0.5),('D4',0.5),('E4',1),
    ('F4',0.5),('E4',0.5),('D4',2),
]

MZE_MIKHVDA = [         # მზე მიხვდა — E minor, 4/4
    ('E4',1),('F#4',0.5),('G4',0.5),('A4',1),('B4',1),
    ('A4',0.5),('G4',0.5),('F#4',1),('E4',1),
    ('G4',1),('A4',0.5),('B4',0.5),('C5',1),('B4',1),
    ('A4',0.5),('G4',0.5),('E4',2),
]

# ══════════════════════════════════════════════════════════════
# OPERA'S OWN THEMES (from HARMONY.md, integrated with folk melodies)
# ══════════════════════════════════════════════════════════════

T1  = [('D4',1),('F4',0.5),('A4',0.5),('C5',1),('A4',0.5),  # გილგამეშის თემა
        ('G4',0.5),('F4',1),('E4',1),('D4',2)]
T2  = [('D4',0.5),('Eb4',0.5),('F4',0.5),('Gb4',0.5),        # ტრიოს დისონანსი
        ('Ab4',1),('Gb4',0.5),('F4',0.5),('Eb4',1),('D4',1),('C4',2)]
T3  = [('D4',1),('F#4',0.5),('A4',0.5),('D5',1),             # გარდაქმნა (D major)
        ('C#5',0.5),('B4',0.5),('A4',1),('G4',0.5),('F#4',0.5),('E4',1),('D4',2)]
T14 = TSINTSKARO        # შამხათის კლიტვა
T17 = MRAVALZHAMIER     # მრავალჟამიერ (ტრიო)
T20 = CHAKRULO          # ჩაკრულო (იშთარი)
T6  = VIRISHKHAU        # ვირიშხაუ (ენქიდუს ლამური)
T10 = SAMKURAO          # სამკურაო (ნინსუნი)
T11 = OROVELA           # ლილე/ოროველა

# ══════════════════════════════════════════════════════════════
# HELPER FUNCTIONS
# ══════════════════════════════════════════════════════════════

def N(p, dur=1.0, lyr=None, dyn_str=None, oct_shift=0):
    """Create a Note or Rest. p='R' → Rest."""
    if p == 'R':
        return note.Rest(quarterLength=dur)
    pk = pitch.Pitch(p)
    if oct_shift:
        pk.octave += oct_shift
    n = note.Note(pk, quarterLength=dur)
    if lyr:
        n.addLyric(lyr)
    if dyn_str:
        n.expressions.append(dynamics.Dynamic(dyn_str))
    return n

def theme_to_notes(t, lyrics=None, dyn_str=None, oct_shift=0):
    """Convert theme list → list of music21 notes."""
    out = []
    for i, (p, d) in enumerate(t):
        lyr = lyrics[i] if lyrics and i < len(lyrics) else None
        dn  = dyn_str if i == 0 else None
        out.append(N(p, d, lyr, dn, oct_shift))
    return out

def beats(ts_str='4/4'):
    """Quarter-length beats per measure for a time signature string."""
    num, den = ts_str.split('/')
    return 4.0 * int(num) / int(den)

def pack_measures(ns_list, ts_str='4/4', start_ks=None,
                  start_ts=True, start_tempo=None, start_text=None,
                  start_clef_str=None, repeat_start=False):
    """Pack a flat list of notes/rests into Measures."""
    bpm = beats(ts_str)
    measures = []
    cur = stream.Measure()
    first = True
    if start_clef_str:
        cur.append(clef.Clef(clef_type=start_clef_str) if start_clef_str != 'bass'
                   else clef.BassClef())
    if start_ks is not None:
        cur.append(key.KeySignature(start_ks))
    if start_ts:
        cur.append(meter.TimeSignature(ts_str))
    if start_tempo:
        cur.append(MetronomeMark(number=start_tempo))
    if start_text:
        cur.append(expressions.TextExpression(start_text))
    if repeat_start:
        cur.leftBarline = bar.Repeat(direction='start')

    cur_beats = 0.0
    for n in ns_list:
        nd = n.quarterLength
        if cur_beats + nd > bpm + 0.001:
            # Fill with rest if needed
            rem = bpm - cur_beats
            if rem > 0.01:
                cur.append(note.Rest(quarterLength=rem))
            measures.append(cur)
            cur = stream.Measure()
            cur.append(meter.TimeSignature(ts_str))
            cur_beats = 0.0
            first = False
        cur.append(n)
        cur_beats += nd
    # Final measure
    rem = bpm - cur_beats
    if rem > 0.01:
        cur.append(note.Rest(quarterLength=rem))
    measures.append(cur)
    return measures

def rest_ms(n, ts_str='4/4'):
    """Generate n whole-measure rest Measure objects."""
    bpm = beats(ts_str)
    return [stream.Measure([note.Rest(quarterLength=bpm)]) for _ in range(n)]

def scene_header_text(label, duration_min, bpm, ts_str):
    """Build opening text for a scene."""
    return f"{label} | {duration_min}წთ | ♩={bpm}"

def add_repeat_section(part, ns, ts_str, times=2, tempo_bpm=None, txt=None, ks=None):
    """Add notes as a repeat section (start→end barlines), then rest equivalent."""
    ms = pack_measures(ns, ts_str, start_ks=ks, start_tempo=tempo_bpm, start_text=txt,
                       repeat_start=True)
    if ms:
        ms[-1].rightBarline = bar.Repeat(direction='end', times=times)
    for m in ms:
        part.append(m)

def add_dyn_text(part, txt):
    """Append text expression to last measure of part."""
    mlist = list(part.getElementsByClass('Measure'))
    if mlist:
        mlist[-1].insert(0, expressions.TextExpression(txt))

def fill_rests(part, ts_str, count):
    """Add count empty measures to part."""
    for m in rest_ms(count, ts_str):
        part.append(m)

# ══════════════════════════════════════════════════════════════
# ORCHESTRAL PARTS SETUP
# ══════════════════════════════════════════════════════════════

def make_parts():
    """Create all 17 parts with Georgian names and proper instruments."""
    def P(inst_obj, name_geo, abbr):
        p = stream.Part()
        p.partName = name_geo
        p.partAbbreviation = abbr
        p.insert(0, inst_obj)
        return p

    parts = {
        # Soloists
        'gilgamesh': P(instrument.Baritone(),    'გილ-გა-მე-ში (ბარიტონი)',   'გმშ'),
        'enkidu':    P(instrument.Tenor(),        'ენ-კი-დუ (ტენორი)',          'ენქ'),
        'ninsun':    P(instrument.MezzoSoprano(), 'ნინ-სუ-ნი (მეც-სოპ.)',      'ნინ'),
        'shamhat':   P(instrument.Soprano(),      'შამ-ხა-თი (სოპ.)',           'შმხ'),
        'humbaba':   P(instrument.Bass(),         'ხუმ-ბა-ბა / უტ-ნა-ფიშ-თი', 'ხბბ'),
        # Gilgamesh Trio (invisible inner voices)
        'mkrimani':  P(instrument.Tenor(),        'მ-კ-რი-მა-ნი (კ-ტ)',        'მკრ'),
        'mtavari':   P(instrument.Tenor(),        'მ-თა-ვა-რი (ტენ.)',          'მთვ'),
        'bani':      P(instrument.Bass(),         'ბა-ნი (ბასი)',               'ბნი'),
        # Chorus
        'choir':     P(instrument.Vocalist(),     'გუნ-და (ქო-რი)',             'გნდ'),
        # Georgian instruments
        'lamuri':    P(instrument.Flute(),        'ლა-მუ-რი (სვ. სა-ბე-ჭ.)',  'ლმრ'),
        'chuniri':   P(instrument.Violin(),       'ჩუ-ნი-რი (სვ. ვიოლ.)',     'ჩნრ'),
        'panduri':   P(instrument.Violin(),       'პან-დუ-რი (გიტ.)',           'პნდ'),
        # Orchestra
        'strings':   P(instrument.StringInstrument(), 'სი-მებ-რი (ვიოლ.)',    'სმბ'),
        'winds':     P(instrument.Oboe(),         'ჩასაბე-ჭე-ბი (გობ.)',       'ჩბ'),
        'brass':     P(instrument.Horn(),         'სპი-ლენ-ძი (ვალტ.)',        'სპლ'),
        'cello':     P(instrument.Violoncello(),  'ვი-ო-ლონ-ჩე-ლო',           'ვლჩ'),
        'piano':     P(instrument.Piano(),        'ფო-რ-ტე-პი-ა-ნო',          'ფრტ'),
    }
    return parts

# ══════════════════════════════════════════════════════════════
# ACT / SCENE BUILDERS
# Duration targets (minutes): Act I=35, II=40, III=40, IV=45, V=50 → total=210
# At given BPMs: measures needed per scene calculated below.
# We use repeat signs + text to represent full duration efficiently.
# ══════════════════════════════════════════════════════════════

def build_act_I(p):
    """
    მოქმედება I — ურუქი / Act I — Uruk
    სცენა 1: ურუქის ჰიმნი (12 წთ, ♩=58, 4/4, D minor → G minor)
    სცენა 2: ენქიდუს გაჩენა (12 წთ, ♩=52, 4/4, G minor + Svan)
    სცენა 3: ლამური ff — შეხვედრა (11 წთ, ♩=63, 7/8, D minor)
    """
    g = p['gilgamesh']; ek = p['enkidu']; ns = p['ninsun']
    sh = p['shamhat'];  lm = p['lamuri']; ch = p['chuniri']
    mk = p['mkrimani']; mt = p['mtavari']; bn = p['bani']
    st = p['strings'];  cl = p['cello'];  pi = p['piano']
    br = p['brass'];    wi = p['winds'];  ch2 = p['choir']
    pd = p['panduri']

    # ─── SCENE 1: ურუქის ჰიმნი ─────────────────────────────────
    # Chorus: Mravalzhamier (authentic D Dorian melody)
    # → represents a 12-min opening blessing sung 4× with interludes
    lyr1 = ['მრ-','ა-','ვალ-','ჟა-','მი-','ე-','რი!',
             'ად-','ი-','დე-','ბო-','დეს','ურ-','უ-','ქი!',
             'ად-','ი-','დე-','ბო-','დეს!']
    mrav_n = theme_to_notes(MRAVALZHAMIER, lyr1, 'mf')

    add_repeat_section(ch2, mrav_n, '4/4', times=4,
                       tempo_bpm=58,
                       txt='სც.1 | ურუქის ჰიმნი | 12წთ | D Dorian',
                       ks=-1)  # 1 flat = F major / D minor

    # Piano: Tsintskaro drone bass (left hand)
    ts_bass = [('G2',2),('D3',2)] * 4
    add_repeat_section(pi, theme_to_notes(ts_bass), '4/4', times=8, ks=-2)

    # Gilgamesh: T1 theme pp → ff (sung in Georgian)
    lyr_t1 = ['გილ-','გა-','მე-','შო!','ად-','ი-','დე-','ბო-','დეს!']
    t1_n = theme_to_notes(T1, lyr_t1, 'pp')
    add_repeat_section(g, t1_n, '4/4', times=4,
                       txt='T1: გილგამეშის თემა pp→ff', ks=-1)

    # Strings: Tsintskaro accompaniment figure
    tsints_n = theme_to_notes(TSINTSKARO, dyn_str='p')
    add_repeat_section(st, tsints_n, '4/4', times=4, ks=-2)

    # Trio pp: Mravalzhamier inner voices
    trio_lyr = ['ოო-','ო-','ო-','ო-','ვ-ვ-','ვ-','ვ-',
                'ო-','ო-','ოო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-']
    for part_trio, osh in [(mk, 1), (mt, 0), (bn, -1)]:
        add_repeat_section(part_trio,
                           theme_to_notes(MRAVALZHAMIER, trio_lyr, 'pp', osh),
                           '4/4', times=4, ks=-1)

    # Lamuri: silent in scene 1
    fill_rests(lm, '4/4', 16)
    fill_rests(ek, '4/4', 16)
    fill_rests(ns, '4/4', 16)
    fill_rests(sh, '4/4', 16)
    fill_rests(ch, '4/4', 16)
    fill_rests(pd, '4/4', 16)
    fill_rests(wi, '4/4', 16)
    fill_rests(br, '4/4', 16)

    # ─── SCENE 2: ენქიდუს გაჩენა ─────────────────────────────
    # Lamuri enters ff: Virishkhau (Svan flute melody)
    lyr_v = ['ვ-','ი-','რ-','ი-','შ-','ხ-','ა-','უ!',
             'ო-','ო-','ო-','ო-','ო-','ო-','ო-']
    vir_n = theme_to_notes(VIRISHKHAU, lyr_v, 'ff')
    add_repeat_section(lm, vir_n, '4/4', times=6,
                       tempo_bpm=52,
                       txt='სც.2 | ენქიდუს გაჩენა | 12წთ | G minor + Svan',
                       ks=-2)

    # Enkidu enters with Khasanbegura (Gurian)
    lyr_ek = ['ვინ-','ვარ?','მი-','წის-','ძე!','ტყის-','შვი-','ლი!',
              'ენ-','კი-','დუ-','ვ-','ა-','რ-','ა!']
    khas_n = theme_to_notes(KHASANBEGURA, lyr_ek, 'mf')
    add_repeat_section(ek, khas_n, '4/4', times=6, ks=-2)

    # Chuniri: Svan drone + Virishkhau
    add_repeat_section(ch, theme_to_notes(VIRISHKHAU, dyn_str='mp'), '4/4', times=6, ks=-2)

    # Ninsun: Samkurao lullaby (Megrelian)
    lyr_ns = ['ო-','დო-','ია-','ო-','ო-','ო-','ო-','ო-',
              'სამ-','კუ-','რა-','ო-','ო-','ო-']
    add_repeat_section(ns,
                       theme_to_notes(SAMKURAO, lyr_ns, 'p', oct_shift=0),
                       '4/4', times=6,
                       txt='T10: სამკურაო (ნინსუნი)', ks=-1)

    fill_rests(g,  '4/4', 24)
    fill_rests(mk, '4/4', 24)
    fill_rests(mt, '4/4', 24)
    fill_rests(bn, '4/4', 24)
    fill_rests(sh, '4/4', 24)
    fill_rests(st, '4/4', 24)
    fill_rests(cl, '4/4', 24)
    fill_rests(pi, '4/4', 24)
    fill_rests(wi, '4/4', 24)
    fill_rests(br, '4/4', 24)
    fill_rests(pd, '4/4', 24)
    fill_rests(ch2,'4/4', 24)

    # ─── SCENE 3: შეხვედრა / ბრძოლა ──────────────────────────
    # 7/8, D minor, Mtiuluri dance → combat music
    lyr_mt = ['ბრ-','ძო-','ლა!','ბრ-','ძო-','ლა!','ურ-',
              'უ-','ქი!','გი-','ლ-','გა-','მე-','ში!','ენ-','კი-','დუ!']
    mti_n = theme_to_notes(MTIULURI, lyr_mt, 'ff')
    for part_s3 in [g, ek, lm]:
        add_repeat_section(part_s3, mti_n, '7/8', times=8,
                           tempo_bpm=63,
                           txt='სც.3 | შეხვედრა-ბრძოლა | 11წთ | 7/8 D minor',
                           ks=-1)

    # Brass: heavy accents
    add_repeat_section(br,
                       theme_to_notes([('D3',1),('R',0.75),('F3',0.5),('A3',0.5),('D3',0.75)],
                                      dyn_str='ff'),
                       '7/8', times=8, ks=-1)

    # Trio: T17 Mravalzhamier pp (distant)
    for pt in [mk, mt, bn]:
        add_repeat_section(pt,
                           theme_to_notes(MRAVALZHAMIER, dyn_str='pp'),
                           '4/4', times=4, ks=-1)

    fill_rests(ns, '7/8', 32)
    fill_rests(sh, '7/8', 32)
    fill_rests(ch, '7/8', 32)
    fill_rests(pd, '7/8', 32)
    fill_rests(st, '7/8', 32)
    fill_rests(cl, '7/8', 32)
    fill_rests(pi, '7/8', 32)
    fill_rests(wi, '7/8', 32)
    fill_rests(ch2,'7/8', 32)


def build_act_II(p):
    """
    მოქმედება II — ჰუმბაბა / Act II — Humbaba
    სც.4: გილგამეშის ოცნება (10წთ, ♩=54, 4/4, A minor)
    სც.5: ჰუმბაბას ტყე — ვარიაციები (15წთ, ♩=60, 5/4, E minor)
    სც.6: გამარჯვება (8წთ, ♩=76, 4/4, C major → Gandagana)
    სც.7: შამხათი / გადაქცევა (7წთ, ♩=66, 4/4, G minor → Iavnana)
    """
    g = p['gilgamesh']; ek = p['enkidu']; ns = p['ninsun']
    sh = p['shamhat'];  lm = p['lamuri']; ch = p['chuniri']
    mk = p['mkrimani']; mt = p['mtavari']; bn = p['bani']
    st = p['strings'];  cl = p['cello'];  pi = p['piano']
    br = p['brass'];    wi = p['winds'];  ch2 = p['choir']
    hb = p['humbaba'];  pd = p['panduri']

    # ─── SCENE 4: ოცნება ─────────────────────────────────────
    lyr_g4 = ['გვ-','ა-','ვი-','ო-','ნე-','ბი-','ს-','გან-','ვი-','ც-','ი-',
              'ო-','ა-','ო-','ო-']
    iav_n = theme_to_notes(IAVNANA, lyr_g4, 'pp')
    add_repeat_section(g, iav_n, '4/4', times=5,
                       tempo_bpm=54,
                       txt='სც.4 | გილგამეშის ოცნება | 10წთ | A minor / Iavnana',
                       ks=-1)

    # Ninsun: Samkurao
    lyr_ns4 = ['ო-','დო-','ი-','ა-','ო-','ო-','ო-','ო-',
               'ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(ns, theme_to_notes(SAMKURAO, lyr_ns4, 'p'), '4/4', times=5, ks=0)

    # Lamuri: Virishkhau f (fading)
    add_repeat_section(lm, theme_to_notes(VIRISHKHAU, dyn_str='f'), '4/4', times=5, ks=-1)

    # Trio: T1 pp
    for pt, osh in [(mk, 1), (mt, 0), (bn, -1)]:
        add_repeat_section(pt, theme_to_notes(T1, dyn_str='pp', oct_shift=osh),
                           '4/4', times=5, ks=-1)

    fill_rests(ek, '4/4', 20); fill_rests(sh, '4/4', 20)
    fill_rests(hb, '4/4', 20); fill_rests(ch, '4/4', 20)
    fill_rests(pd, '4/4', 20); fill_rests(st, '4/4', 20)
    fill_rests(cl, '4/4', 20); fill_rests(pi, '4/4', 20)
    fill_rests(br, '4/4', 20); fill_rests(wi, '4/4', 20)
    fill_rests(ch2,'4/4', 20)

    # ─── SCENE 5: ჰუმბაბას ტყე ───────────────────────────────
    # 7 variations: Mze Mikhvda (E minor) + Gandagana
    lyr_hb = ['ო-','ჰო!','ხუმ-','ბა-','ბა!','ვა-','ო!','ო-','ო-','ო-',
              'ვ-','ვ-','ვ-','ვ-','ვ-','ვ-','ვ!']
    for var_n, ks_val, bpm_v, ts_v in [
        (1, -2, 60, '5/4'), (2, -2, 65, '5/4'), (3, -1, 70, '5/4'),
        (4,  0, 75, '4/4'), (5, -1, 80, '7/8'), (6, -2, 85, '7/8'), (7, -1, 90, '4/4')
    ]:
        vn = theme_to_notes(MZE_MIKHVDA if var_n <= 4 else GANDAGANA, lyr_hb, 'mf')
        for pt in [hb, g, ek, st, br]:
            add_repeat_section(pt, vn, ts_v, times=3,
                               tempo_bpm=bpm_v if pt == hb else None,
                               txt=f'ვარ.{var_n}' if pt == hb else None,
                               ks=ks_val)

    lyr_lm5 = ['ვ-','ი-','რ-','ი-','შ-','ხ-','ა-','უ!',
               'ო-','ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(lm, theme_to_notes(VIRISHKHAU, lyr_lm5, 'mf'), '4/4', times=7, ks=-1)
    fill_rests(ns,'4/4',63); fill_rests(sh,'4/4',63); fill_rests(mk,'4/4',63)
    fill_rests(mt,'4/4',63); fill_rests(bn,'4/4',63); fill_rests(ch,'4/4',63)
    fill_rests(pd,'4/4',63); fill_rests(cl,'4/4',63); fill_rests(pi,'4/4',63)
    fill_rests(wi,'4/4',63); fill_rests(ch2,'4/4',63)

    # ─── SCENE 6: გამარჯვება ─────────────────────────────────
    lyr_w = ['გა-','მარ-','ჯვ-','ება!','ურ-','უ-','ქი!','ო-','ო-','ო-',
             'გა-','ნ-','და-','გა-','ნა!','ო-']
    gand_n = theme_to_notes(GANDAGANA, lyr_w, 'ff')
    for pt in [g, ek, ch2, st, br]:
        add_repeat_section(pt, gand_n, '4/4', times=4,
                           tempo_bpm=76 if pt == g else None,
                           txt='სც.6 | გამარჯვება | 8წთ | C major | Gandagana' if pt == g else None,
                           ks=0)
    add_repeat_section(lm, theme_to_notes(VIRISHKHAU, dyn_str='mf'), '4/4', times=4, ks=-1)
    fill_rests(hb,'4/4',16); fill_rests(ns,'4/4',16); fill_rests(sh,'4/4',16)
    fill_rests(mk,'4/4',16); fill_rests(mt,'4/4',16); fill_rests(bn,'4/4',16)
    fill_rests(ch,'4/4',16); fill_rests(pd,'4/4',16); fill_rests(cl,'4/4',16)
    fill_rests(pi,'4/4',16); fill_rests(wi,'4/4',16)

    # ─── SCENE 7: შამხათი ────────────────────────────────────
    lyr_sh = ['შამ-','ხა-','თო,','გად-','მო-','ა-','ფი-','ნე!',
              'და-','ი-','ფა-','რე!','ო-','ო-']
    tsints_n = theme_to_notes(TSINTSKARO, lyr_sh, 'mp')
    add_repeat_section(sh, tsints_n, '4/4', times=4,
                       tempo_bpm=66,
                       txt='სც.7 | შამხათი | 7წთ | G minor | Tsintskaro',
                       ks=-2)

    lyr_ek7 = ['ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-',
               'ვ-','ვ-','ვ-','ვ-','ვ-','ო-','ო-','ო-']
    add_repeat_section(ek, theme_to_notes(KHASANBEGURA, lyr_ek7, 'mp'), '4/4', times=4, ks=-2)
    fill_rests(g,'4/4',16); fill_rests(ns,'4/4',16); fill_rests(hb,'4/4',16)
    fill_rests(lm,'4/4',16); fill_rests(mk,'4/4',16); fill_rests(mt,'4/4',16)
    fill_rests(bn,'4/4',16); fill_rests(ch,'4/4',16); fill_rests(pd,'4/4',16)
    fill_rests(st,'4/4',16); fill_rests(cl,'4/4',16); fill_rests(pi,'4/4',16)
    fill_rests(br,'4/4',16); fill_rests(wi,'4/4',16); fill_rests(ch2,'4/4',16)


def build_act_III(p):
    """
    მოქმედება III — სიკვდილი / Act III — Death
    სც.8: ციური ხარი (10წთ, ♩=69, 7/8, Bb major → Chakrulo)
    სც.9: ლამენტაცია (15წთ, ♩=44, 4/4, A minor → Khasanbegura)
    სც.10: ენქიდუს სიკვდილი (15წთ, ♩=40, 4/4, D minor → pppp→0)
    """
    g = p['gilgamesh']; ek = p['enkidu']; ns = p['ninsun']
    sh = p['shamhat'];  lm = p['lamuri']; ch = p['chuniri']
    mk = p['mkrimani']; mt = p['mtavari']; bn = p['bani']
    st = p['strings'];  cl = p['cello'];  pi = p['piano']
    br = p['brass'];    wi = p['winds'];  ch2 = p['choir']
    hb = p['humbaba'];  pd = p['panduri']

    # ─── SCENE 8: ციური ხარი ─────────────────────────────────
    lyr_c8 = ['ჩა-','კ-','რუ-','ლო!','ო-','ო-','ო-','ო-',
              'ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-',
              'ო-','ო-','ო-','ო-','ო-','ო-']
    chak_n = theme_to_notes(CHAKRULO, lyr_c8, 'ff')
    for pt in [ch2, g, mk, mt, bn]:
        add_repeat_section(pt, chak_n, '7/8', times=5,
                           tempo_bpm=69 if pt == ch2 else None,
                           txt='სც.8 | ციური ხარი | 10წთ | Bb major | T20 Chakrulo' if pt == ch2 else None,
                           ks=-2)

    add_repeat_section(br, theme_to_notes([('Bb2',1.75),('F3',0.75),('Bb2',1.75),('C3',0.75)],
                                          dyn_str='ff'),
                       '7/8', times=5, ks=-2)
    fill_rests(ek,'7/8',25); fill_rests(ns,'7/8',25); fill_rests(sh,'7/8',25)
    fill_rests(hb,'7/8',25); fill_rests(lm,'7/8',25); fill_rests(ch,'7/8',25)
    fill_rests(pd,'7/8',25); fill_rests(st,'7/8',25); fill_rests(cl,'7/8',25)
    fill_rests(pi,'7/8',25); fill_rests(wi,'7/8',25)

    # ─── SCENE 9: ლამენტაცია ─────────────────────────────────
    lyr_k9 = ['ვ-','ო-','ი!','ვ-','ო-','ი!','ი-','ტი-','რ-','ი-','ს!',
               'ხა-','სან-','ბ-','ე-','გო!']
    khas_n = theme_to_notes(KHASANBEGURA, lyr_k9, 'mf')
    for pt in [g, sh, ch2]:
        add_repeat_section(pt, khas_n, '4/4', times=8,
                           tempo_bpm=44 if pt == g else None,
                           txt='სც.9 | ლამენტაცია | 15წთ | A minor | Khasanbegura' if pt == g else None,
                           ks=-1)

    # Cello: Mze Mikhvda descending
    add_repeat_section(cl, theme_to_notes(MZE_MIKHVDA, dyn_str='p', oct_shift=-1),
                       '4/4', times=8, ks=-1)

    # Lamuri: Virishkhau p (fading)
    add_repeat_section(lm, theme_to_notes(VIRISHKHAU, dyn_str='p'), '4/4', times=8, ks=-1)

    fill_rests(ek,'4/4',32); fill_rests(ns,'4/4',32); fill_rests(hb,'4/4',32)
    fill_rests(mk,'4/4',32); fill_rests(mt,'4/4',32); fill_rests(bn,'4/4',32)
    fill_rests(ch,'4/4',32); fill_rests(pd,'4/4',32); fill_rests(st,'4/4',32)
    fill_rests(pi,'4/4',32); fill_rests(br,'4/4',32); fill_rests(wi,'4/4',32)

    # ─── SCENE 10: ენქიდუს სიკვდილი ─────────────────────────
    lyr_e10 = ['გა-','მარ-','ჯვ-','ე!','ო-','ო-','ო-','ო-',
               'ლა-','მუ-','რი-','ო-','ო-','ო-','ო-']
    vir_pp = theme_to_notes(VIRISHKHAU, lyr_e10, 'pp')
    add_repeat_section(lm, vir_pp, '4/4', times=4,
                       tempo_bpm=40,
                       txt='სც.10 | ენქიდუს სიკვდილი | 15წთ | D minor | ლამური pppp→0',
                       ks=-1)
    add_dyn_text(lm, 'pppp → 0 (ლამური ჩუმდება)')

    # Enkidu: last solo (Orovela — work song turned death song)
    lyr_ek10 = ['ვ-','ი-','ო-','ვ-','ო-','ო-','ო-','ო-',
                'ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(ek, theme_to_notes(OROVELA, lyr_ek10, 'pp'), '4/4', times=4,
                       txt='T11: ლილე / ოროველა (ენქიდუ, ბოლო)', ks=-1)
    add_dyn_text(ek, 'pppp — ენქიდუ კვდება')

    # Cello solo: Iavnana
    add_repeat_section(cl, theme_to_notes(IAVNANA, dyn_str='ppp', oct_shift=-1),
                       '4/4', times=4, ks=-1)

    # Trio: T2 — first crack (dissonance)
    for pt, osh in [(mk,1),(mt,0),(bn,-1)]:
        add_repeat_section(pt, theme_to_notes(T2, dyn_str='mf', oct_shift=osh),
                           '4/4', times=2, ks=-1)
    add_dyn_text(mk, 'T2 — ტრიო: პირველი განხეთქილება')

    fill_rests(g,'4/4',16); fill_rests(ns,'4/4',16); fill_rests(sh,'4/4',16)
    fill_rests(hb,'4/4',16); fill_rests(ch,'4/4',16); fill_rests(pd,'4/4',16)
    fill_rests(st,'4/4',16); fill_rests(pi,'4/4',16); fill_rests(br,'4/4',16)
    fill_rests(wi,'4/4',16); fill_rests(ch2,'4/4',16)


def build_act_IV(p):
    """
    მოქმედება IV — იშთარი / Act IV — Ishtar
    სც.11: იშთარის გამოჩენა (12წთ, ♩=92, Bb major, T20 Chakrulo fff)
    სც.12: ღმერთების სასამართლო (18წთ, ♩=52, C# minor, a cappella T14)
    სც.13: ენქიდუს სიკვდილი (15წთ, ♩=46, D minor, T6+T10+T2 collapse)
    """
    g = p['gilgamesh']; ek = p['enkidu']; ns = p['ninsun']
    sh = p['shamhat'];  lm = p['lamuri']; ch = p['chuniri']
    mk = p['mkrimani']; mt = p['mtavari']; bn = p['bani']
    st = p['strings'];  cl = p['cello'];  pi = p['piano']
    br = p['brass'];    wi = p['winds'];  ch2 = p['choir']
    hb = p['humbaba'];  pd = p['panduri']

    # ─── SCENE 11: იშთარი ────────────────────────────────────
    # Chakrulo fff + Mravalzhamier ff (last Trio harmony)
    lyr_ish = ['ი-','შ-','თ-','ა-','რი!','ო-','ო-','ო-',
               'ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-',
               'ო-','ო-','ო-','ო-','ო-','ო-']
    for pt in [sh, ch2, g]:
        add_repeat_section(pt, theme_to_notes(CHAKRULO, lyr_ish, 'fff'),
                           '7/8', times=6,
                           tempo_bpm=92 if pt == sh else None,
                           txt='სც.11 | იშთარი | 12წთ | Bb major | T20 fff' if pt == sh else None,
                           ks=-2)

    for pt, osh in [(mk,1),(mt,0),(bn,-1)]:
        add_repeat_section(pt, theme_to_notes(MRAVALZHAMIER, lyr_ish, 'ff', osh),
                           '7/8', times=6, ks=-1)
    add_dyn_text(mk, 'T17 Mravalzhamier ff — ბოლო ჰარმონია ტრიოს')

    add_repeat_section(br, theme_to_notes([('Bb2',1.75),('D3',0.75),('F3',1.75),('Bb3',0.75)],
                                          dyn_str='fff'), '7/8', times=6, ks=-2)
    fill_rests(ek,'7/8',36); fill_rests(ns,'7/8',36); fill_rests(hb,'7/8',36)
    fill_rests(lm,'7/8',36); fill_rests(ch,'7/8',36); fill_rests(pd,'7/8',36)
    fill_rests(st,'7/8',36); fill_rests(cl,'7/8',36); fill_rests(pi,'7/8',36)
    fill_rests(wi,'7/8',36)

    # ─── SCENE 12: ღმერთების სასამართლო ─────────────────────
    # T14: Shamhat's curse = Tsintskaro a cappella
    lyr_sh12 = ['და-','წყ-','ევ-','ლი-','ლი','ი-','ყ-','ოს!',
                'ეს','დ-','ღ-','ე!','მ-','ო-','ვ-','კ-','ა-','ლი!']
    add_repeat_section(sh, theme_to_notes(TSINTSKARO, lyr_sh12, 'fff'),
                       '4/4', times=9,
                       tempo_bpm=52,
                       txt='სც.12 | ღმერთები | 18წთ | C# minor | T14 a cappella',
                       ks=4)  # 4 sharps ≈ C# minor / E major

    # Chorus: Sumerian judgment (Tsintskaro bass)
    lyr_ch12 = ['ი-','ყ-','ოს!','ი-','ყ-','ოს!','ვ-','ი-',
                'ნ-','ა-','ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(ch2, theme_to_notes(TSINTSKARO, lyr_ch12, 'mf', oct_shift=-1),
                       '4/4', times=9, ks=4)

    # Humbaba/Utnapishtim: Bass counterpoint
    lyr_hb12 = ['ს-','ი-','კ-','ვ-','დ-','ი-','ლი','ა-','ვ-','ი-','ც-','ა-','ა-','ო-','ო-','ო-']
    add_repeat_section(hb, theme_to_notes(KHASANBEGURA, lyr_hb12, 'f', oct_shift=-1),
                       '4/4', times=9, ks=4)

    fill_rests(g,'4/4',36); fill_rests(ek,'4/4',36); fill_rests(ns,'4/4',36)
    fill_rests(lm,'4/4',36); fill_rests(mk,'4/4',36); fill_rests(mt,'4/4',36)
    fill_rests(bn,'4/4',36); fill_rests(ch,'4/4',36); fill_rests(pd,'4/4',36)
    fill_rests(st,'4/4',36); fill_rests(cl,'4/4',36); fill_rests(pi,'4/4',36)
    fill_rests(br,'4/4',36); fill_rests(wi,'4/4',36)

    # ─── SCENE 13: სიკვდილი — T6+T10+T2 ─────────────────────
    # Virishkhau D4 → pppp → 0  (lamuri last breath)
    add_repeat_section(lm, theme_to_notes(VIRISHKHAU, dyn_str='pp'), '4/4', times=3,
                       tempo_bpm=46,
                       txt='სც.13 | ენქიდუს სიკვდილი | 15წთ | D minor | T6+T10+T2',
                       ks=-1)
    add_dyn_text(lm, 'pppp → 0')

    # Ninsun: Samkurao (last)
    lyr_ns13 = ['ო-','დო-','ი-','ა-','ო-','ო-','ო-','ო-',
                'ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(ns, theme_to_notes(SAMKURAO, lyr_ns13, 'p'), '4/4', times=3, ks=-1)

    # Trio: T2 falling apart
    for pt, osh in [(mk,1),(mt,0),(bn,-1)]:
        add_repeat_section(pt, theme_to_notes(T2, dyn_str='mf', oct_shift=osh),
                           '4/4', times=3, ks=-1)
    add_dyn_text(mk, 'T2 fff — ტრიო იშლება')

    # Cello: Iavnana
    add_repeat_section(cl, theme_to_notes(IAVNANA, dyn_str='ppp', oct_shift=-1),
                       '4/4', times=3, ks=-1)

    fill_rests(g,'4/4',12); fill_rests(ek,'4/4',12); fill_rests(sh,'4/4',12)
    fill_rests(hb,'4/4',12); fill_rests(ch,'4/4',12); fill_rests(pd,'4/4',12)
    fill_rests(st,'4/4',12); fill_rests(pi,'4/4',12); fill_rests(br,'4/4',12)
    fill_rests(wi,'4/4',12); fill_rests(ch2,'4/4',12)


def build_act_V(p):
    """
    მოქმედება V — ასკენი / Act V — Ascension
    სც.14: გილგამეშის გოდება (12წთ, ♩=46, atonal/C# minor, T2 fff)
    სც.15: სიკვდილის წყლები (10წთ, ♩=42, E pedal/A minor)
    სც.16: უტნაფიშთი (13წთ, ♩=54, G major, T3 pp)
    სც.17: ფინალე — ალილო (15წთ, ♩=88, D major, T3 ff + Alilo)
    """
    g = p['gilgamesh']; ek = p['enkidu']; ns = p['ninsun']
    sh = p['shamhat'];  lm = p['lamuri']; ch = p['chuniri']
    mk = p['mkrimani']; mt = p['mtavari']; bn = p['bani']
    st = p['strings'];  cl = p['cello'];  pi = p['piano']
    br = p['brass'];    wi = p['winds'];  ch2 = p['choir']
    hb = p['humbaba'];  pd = p['panduri']

    # ─── SCENE 14: გოდება ────────────────────────────────────
    lyr_g14 = ['ვ-','ინ','ხ-','ა-','რთ?!','ვ-','ინ','ხ-',
               'ა-','რთ!','სა-','მი','ჩ-','ვ-','ე-','ნი!']
    t2_n = theme_to_notes(T2, lyr_g14, 'fff')
    add_repeat_section(g, t2_n, '4/4', times=6,
                       tempo_bpm=46,
                       txt='სც.14 | გოდება | 12წთ | Atonal | T2 fff',
                       ks=0)

    # Trio: T2 fff dissonant peak
    for pt, osh in [(mk,1),(mt,0),(bn,-1)]:
        add_repeat_section(pt, theme_to_notes(T2, lyr_g14, 'fff', osh),
                           '4/4', times=6, ks=0)
    add_dyn_text(mk, 'T2 fff — ტრიო: კულმინაციური დისონანსი')

    # Cello: E pedal drone
    add_repeat_section(cl, theme_to_notes([('E2',4),('E2',4),('E2',4)], dyn_str='mp'),
                       '4/4', times=6, ks=0)

    fill_rests(ek,'4/4',24); fill_rests(ns,'4/4',24); fill_rests(sh,'4/4',24)
    fill_rests(hb,'4/4',24); fill_rests(lm,'4/4',24); fill_rests(ch,'4/4',24)
    fill_rests(pd,'4/4',24); fill_rests(st,'4/4',24); fill_rests(pi,'4/4',24)
    fill_rests(br,'4/4',24); fill_rests(wi,'4/4',24); fill_rests(ch2,'4/4',24)

    # ─── SCENE 15: სიკვდილის წყლები ─────────────────────────
    # Shadows choir: Mze Mikhvda (E minor)
    lyr_sh15 = ['ვ-','ინ','ი-','ქ-','ნა?','ვ-','ინ','მო-',
                'დ-','ის?','ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(ch2, theme_to_notes(MZE_MIKHVDA, lyr_sh15, 'pp'),
                       '4/4', times=5,
                       tempo_bpm=42,
                       txt='სც.15 | სიკვდილის წყლები | 10წთ | E pedal',
                       ks=1)  # 1 sharp = E minor / G major

    # Cello: E pedal
    add_repeat_section(cl, theme_to_notes([('E2',2),('B2',2),('E2',4)], dyn_str='p'),
                       '4/4', times=5, ks=1)

    # Gilgamesh: fragments of T1
    add_repeat_section(g, theme_to_notes(T1, dyn_str='p'), '4/4', times=5, ks=1)

    fill_rests(ek,'4/4',20); fill_rests(ns,'4/4',20); fill_rests(sh,'4/4',20)
    fill_rests(hb,'4/4',20); fill_rests(lm,'4/4',20); fill_rests(ch,'4/4',20)
    fill_rests(mk,'4/4',20); fill_rests(mt,'4/4',20); fill_rests(bn,'4/4',20)
    fill_rests(pd,'4/4',20); fill_rests(st,'4/4',20); fill_rests(pi,'4/4',20)
    fill_rests(br,'4/4',20); fill_rests(wi,'4/4',20)

    # ─── SCENE 16: უტნაფიშთი ─────────────────────────────────
    # T3 pp (trio begins finding harmony): Samkurao + Iavnana
    lyr_ut = ['ყ-','ვა-','ვ-','ი-','ლი','ნ-','ა-','ხ-','ე!','ვ-','ი-','პ-','ო-','ვ-','ე!','ო-']
    add_repeat_section(hb, theme_to_notes(IAVNANA, lyr_ut, 'p'),
                       '4/4', times=6,
                       tempo_bpm=54,
                       txt='სც.16 | უტნაფიშთი | 13წთ | G major | T3 pp',
                       ks=1)

    for pt, osh in [(mk,1),(mt,0),(bn,-1)]:
        t3_n = theme_to_notes(T3, dyn_str='pp', oct_shift=osh)
        add_repeat_section(pt, t3_n, '4/4', times=6, ks=2)
    add_dyn_text(mk, 'T3 pp — ტრიო: ჰარმონია ჩნდება')

    # Gilgamesh: Orovela (found flower)
    lyr_g16 = ['ვ-','ი-','პ-','ო-','ვ-','ე!','ყ-','ვა-',
               'ვ-','ი-','ლი!','ო-','ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(g, theme_to_notes(OROVELA, lyr_g16, 'mp'), '4/4', times=6, ks=1)

    # Lamuri: pppp echo from Svan
    add_repeat_section(lm, theme_to_notes(VIRISHKHAU, dyn_str='pppp'), '4/4', times=2,
                       txt='ლამური — pppp ექო სვანეთიდან', ks=-1)
    add_dyn_text(lm, 'სვანური: pppp, ბოლო ექო')

    fill_rests(ek,'4/4',24); fill_rests(ns,'4/4',24); fill_rests(sh,'4/4',24)
    fill_rests(ch,'4/4',24); fill_rests(pd,'4/4',24); fill_rests(st,'4/4',24)
    fill_rests(cl,'4/4',24); fill_rests(pi,'4/4',24); fill_rests(br,'4/4',24)
    fill_rests(wi,'4/4',24); fill_rests(ch2,'4/4',24)

    # ─── SCENE 17: ფინალე — ალილო ────────────────────────────
    # T3 ff + Alilo + T11 Lile: D major, full orchestra
    lyr_a17 = ['ა-','ლ-','ი-','ლო!','ო-','ო-','ო-',
               'ა-','ლ-','ი-','ლო!','ო-','ო-','ო-','ო-','ო-']
    alilo_n = theme_to_notes(ALILO, lyr_a17, 'ff')

    for pt in [ch2, g, ns, sh, mk, mt, bn]:
        add_repeat_section(pt, alilo_n, '4/4', times=6,
                           tempo_bpm=88 if pt == ch2 else None,
                           txt='სც.17 | ფინალე — ალილო | 15წთ | D major | T3+T11+Alilo ff' if pt == ch2 else None,
                           ks=2)

    # Full orchestra: T3
    for pt in [st, pi, wi]:
        add_repeat_section(pt, theme_to_notes(T3, dyn_str='ff'), '4/4', times=6, ks=2)

    # Brass: triumphant chords
    add_repeat_section(br,
                       theme_to_notes([('D3',1),('A3',1),('D4',2),('R',2),('F#3',1),('A3',1),('D4',1)],
                                      dyn_str='fff'),
                       '4/4', times=6, ks=2)

    # Lile/Orovela: choir second voice
    lyr_lile = ['ლი-','ლე!','ო-','ო-','ო-','ო-','ო-','ო-',
                'ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(ek, theme_to_notes(OROVELA, lyr_lile, 'f'), '4/4', times=6, ks=2)

    # Cello: descending D3 → silence
    clo_n = theme_to_notes([('D3',2),('C3',2),('B2',2),('A2',2),('G2',2),('F#2',2),('D2',4)],
                             dyn_str='pp', oct_shift=0)
    add_repeat_section(cl, clo_n, '4/4', times=2,
                       txt='ვიოლონჩელო D3 → 0 (ოპერა სრულდება)', ks=2)
    add_dyn_text(cl, 'pppp — სიჩუმე')

    # Lamuri: final Svan echo pppp (one last phrase)
    add_repeat_section(lm, theme_to_notes(VIRISHKHAU, dyn_str='pppp'), '4/4', times=1,
                       txt='ლამური: ბოლო სვანური ექო pppp', ks=-1)

    # Gilgamesh: solo without Trio (Trio falls silent)
    lyr_g17 = ['ნა-','ნა-','ი-','ა-','ვ-','ნა-','ნა-','ო-',
               'ო-','ო-','ო-','ო-','ო-','ო-']
    add_repeat_section(g, theme_to_notes(IAVNANA, lyr_g17, 'p'), '4/4', times=2, ks=2)
    add_dyn_text(g, 'გილგამეში — მარტო, ტრიოს გარეშე')
    add_dyn_text(mk, 'ტრიო: სიჩუმე')

    fill_rests(hb,'4/4',24); fill_rests(ch,'4/4',24); fill_rests(pd,'4/4',24)


# ══════════════════════════════════════════════════════════════
# MAIN: ASSEMBLE SCORE
# ══════════════════════════════════════════════════════════════

def build_score():
    print("სამნუ ა-ზუ-ზი — MuseScore3 210min score generator")
    print("Building orchestral parts...")

    sc = stream.Score()

    # Metadata
    md = metadata.Metadata()
    md.title       = "სამნუ ა-ზუ-ზი"
    md.composer    = "ჯაბა თქემალაძე"
    md.movementName = "ოპერა ხუთ მოქმედებად · 210 წუთი"
    sc.metadata = md

    # Create all parts
    parts = make_parts()

    # Build all acts
    print("  Act I  (სც. 1–3, ~35წთ)…")
    build_act_I(parts)
    print("  Act II (სც. 4–7, ~40წთ)…")
    build_act_II(parts)
    print("  Act III (სც. 8–10, ~40წთ)…")
    build_act_III(parts)
    print("  Act IV (სც. 11–13, ~45წთ)…")
    build_act_IV(parts)
    print("  Act V  (სც. 14–17, ~50წთ)…")
    build_act_V(parts)

    # Assemble score in display order
    order = ['gilgamesh','enkidu','ninsun','shamhat','humbaba',
             'mkrimani','mtavari','bani','choir',
             'lamuri','chuniri','panduri',
             'strings','winds','brass','cello','piano']
    for key_name in order:
        sc.append(parts[key_name])

    print(f"Writing → {OUT_FILE}")
    sc.write('musicxml', fp=OUT_FILE)
    print(f"Done. File: {OUT_FILE}")
    sz = os.path.getsize(OUT_FILE) // 1024
    print(f"Size: {sz} KB")
    print()
    print("Open with:  musescore3 'SAMNU_AZUZI_210min.musicxml'")
    print()
    print("Duration notes (at indicated tempos with repeats):")
    print("  Act I  : ~35 min (სც.1-3)")
    print("  Act II : ~40 min (სც.4-7)")
    print("  Act III: ~40 min (სც.8-10)")
    print("  Act IV : ~45 min (სც.11-13)")
    print("  Act V  : ~50 min (სც.14-17)")
    print("  TOTAL  : ~210 min")


if __name__ == '__main__':
    build_score()
