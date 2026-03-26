#!/usr/bin/env python3
"""
ŠAMNU AZUZI — Генератор MIDI партитуры
Опера Джабы Ткемаладзе / Opera by Jaba Tkemaladze

Генерирует MIDI-файлы для всех 20 тем (T1–T20)
и полную превью-партитуру оперы в порядке сцен.
"""

import os
import mido
from mido import MidiFile, MidiTrack, Message, MetaMessage

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ─── MIDI utilities ──────────────────────────────────────────────────────────

NOTE_MAP = {'C': 0, 'D': 2, 'E': 4, 'F': 5, 'G': 7, 'A': 9, 'B': 11}

def note_to_midi(s):
    """'D4'→62, 'F#5'→78, 'Bb3'→58, 'Eb5'→75, 'D♭4'→61, 'B♭4'→70 ..."""
    s = s.strip()
    if not s or s[0] not in NOTE_MAP:
        return None
    pc = NOTE_MAP[s[0]]
    i = 1
    acc = 0
    if i < len(s) and s[i] in ('#', '♯'):
        acc = 1;  i += 1
    elif i < len(s) and s[i] in ('b', '♭'):
        acc = -1; i += 1
    try:
        octave = int(s[i:])
    except (ValueError, IndexError):
        return None
    return (octave + 1) * 12 + pc + acc

def bpm_to_tempo(bpm):
    return int(60_000_000 / bpm)

# Duration in ticks (ticks_per_beat = 480)
TPB = 480
Q  = TPB        # quarter
H  = TPB * 2    # half
W  = TPB * 4    # whole  (for "hold")
E  = TPB // 2   # eighth
T3_8 = int(TPB * 1.5)  # dotted quarter (for 5/8)

def make_track(name, channel, instrument, notes, tempo, tpb=TPB,
               velocity=80, note_dur=Q, rest_dur=Q):
    """
    notes: list of tokens — note strings, 'R' (rest), 'H' (hold/extend prev)
    """
    track = MidiTrack()
    track.append(MetaMessage('track_name', name=name, time=0))
    track.append(MetaMessage('set_tempo', tempo=tempo, time=0))
    track.append(Message('program_change', channel=channel,
                         program=instrument, time=0))

    prev_pitch = None
    pending_hold = 0   # extra ticks to add to current note

    i = 0
    while i < len(notes):
        token = notes[i]

        if token == 'R':
            track.append(Message('note_off', channel=channel,
                                 note=0, velocity=0, time=rest_dur))
            i += 1
            continue

        if token == 'H':
            # We'll accumulate holds and apply them retroactively
            # via extra time in note_off — handled below
            pending_hold += W
            i += 1
            continue

        pitch = note_to_midi(token)
        if pitch is None:
            i += 1
            continue

        # How long is this note? peek ahead for H tokens
        dur = note_dur
        j = i + 1
        while j < len(notes) and notes[j] == 'H':
            dur += W
            j += 1

        # note on
        track.append(Message('note_on', channel=channel,
                              note=pitch, velocity=velocity, time=0))
        # note off
        track.append(Message('note_off', channel=channel,
                              note=pitch, velocity=0, time=dur))
        prev_pitch = pitch
        i = j  # skip consumed H tokens

    return track


def save_midi(filename, tracks, tpb=TPB):
    mid = MidiFile(type=1, ticks_per_beat=tpb)
    for t in tracks:
        mid.tracks.append(t)
    path = os.path.join(OUTPUT_DIR, filename)
    mid.save(path)
    print(f"  ✓  {filename}")
    return path


# ─── INSTRUMENT CONSTANTS (General MIDI) ─────────────────────────────────────
VIOLIN      = 40   # chuniri
FLUTE       = 73   # lamuri
PAN_FLUTE   = 75   # svan lamuri (archaic)
GUITAR      = 24   # panduri
CHOIR_AAH   = 52   # choir
VOICE_OOH   = 53   # voices
STRINGS     = 48   # string ensemble
BRASS       = 61   # brass section
PIANO       = 0    # piano reduction
CELLO       = 42   # violoncello


# ═══════════════════════════════════════════════════════════════════════════════
# ТЕМА DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════

def gen_T1():
    """T1 — წინწყარო (ჰარმ.) / Tsintskaro (Harmony) — D major, ♩=72"""
    tempo = bpm_to_tempo(72)
    mk = make_track('Mkrimani (T1)', 0, CHOIR_AAH,
        ['D5','F#5','A5','G5','F#5','E5','D5','C#5','D5'],
        tempo, velocity=82)
    mt = make_track('Mtavari (T1)', 1, VOICE_OOH,
        ['A4','D5','F#5','E5','D5','C#5','D4','B3','A4'],
        tempo, velocity=75)
    ba = make_track('Bani (T1)', 2, VOICE_OOH,
        ['D3','A3','D4','A3','D3','A2','D3','A2','D3'],
        tempo, velocity=70)
    save_midi('T01_Tsintskaro_Harmony.mid', [mk, mt, ba])


def gen_T2():
    """T2 — წინწყარო (დის.) / Tsintskaro (Dissonance) — Atonal, ♩=88"""
    tempo = bpm_to_tempo(88)
    mk = make_track('Mkrimani (T2)', 0, CHOIR_AAH,
        ['C#5','G5','A5','F5','B5','D#5','G#5','E5','F5'],
        tempo, velocity=95)
    mt = make_track('Mtavari (T2)', 1, VOICE_OOH,
        ['A4','G#4','G4','F#4','F4','E4','D#4','D4','C#4'],
        tempo, velocity=88)
    ba = make_track('Bani (T2)', 2, VOICE_OOH,
        ['D3','R','D3','Eb3','D3'],
        tempo, velocity=85)
    save_midi('T02_Tsintskaro_Dissonance.mid', [mk, mt, ba])


def gen_T3():
    """T3 — ალილო / Alilo — D major, ♩=66"""
    tempo = bpm_to_tempo(66)
    mk = make_track('Mkrimani (T3)', 0, CHOIR_AAH,
        ['D5','F#5','A5','G5','F#5','E5','D5','C#5','D5','A4','D5'],
        tempo, velocity=82)
    mt = make_track('Mtavari (T3)', 1, VOICE_OOH,
        ['A4','D5','F#5','E5','D5','C#5','D4','B3','A4','F#4','A4'],
        tempo, velocity=76)
    ba = make_track('Bani (T3)', 2, VOICE_OOH,
        ['D3','A3','D4','A3','D3','A2','D3','A2','D3','D2','D3'],
        tempo, velocity=70)
    save_midi('T03_Alilo.mid', [mk, mt, ba])


def gen_T4():
    """T4 — ზარი (სუფთა) / Zari Pure — A minor, senza misura → slow rubato"""
    tempo = bpm_to_tempo(52)   # free but notated slow
    fl = make_track('Lamuri (T4)', 0, PAN_FLUTE,
        ['D4','E4','G4','A4','G4','E4','D4',
         'R',
         'G4','A4','C5','D5','C5','A4','G4'],
        tempo, velocity=65, note_dur=H)
    save_midi('T04_Zari_Pure.mid', [fl])


def gen_T5():
    """T5 — ზარი (ტრანს.) / Zari Transformation — A minor→major"""
    tempo = bpm_to_tempo(80)
    fl = make_track('Lamuri (T5)', 0, PAN_FLUTE,
        ['D4','E4','G4','A4','B4','A4','G4','F#4','E4','D4'],
        tempo, velocity=72)
    pd = make_track('Panduri (T5)', 1, GUITAR,
        ['A4','B4','C5','D5','E5','D5','C5','B4','A4','G4','A4'],
        tempo, velocity=78)
    save_midi('T05_Zari_Transformation.mid', [fl, pd])


def gen_T6():
    """T6 — ვირიშხაუ / Virishkhau — D minor, ♩=40 (death of Enkidu)"""
    tempo = bpm_to_tempo(40)
    fl = make_track('Lamuri (T6)', 0, PAN_FLUTE,
        ['D4','H','E4','H','G4','H','A4','G4','E4','D4'],
        tempo, velocity=55, note_dur=H)
    tn = make_track('Enkidu (T6)', 1, VOICE_OOH,
        ['A4','G4','E4','D4','C4','A3'],
        tempo, velocity=62, note_dur=H)
    save_midi('T06_Virishkhau.mid', [fl, tn])


def gen_T7():
    """T7 — ნანა / Nana — D minor, ♩=60"""
    tempo = bpm_to_tempo(60)
    ch = make_track('Chuniri+Mezzo (T7)', 0, VIOLIN,
        ['D4','F4','E4','D4','C4','D4','F4','G4','A4','G4','F4','E4','D4'],
        tempo, velocity=68)
    save_midi('T07_Nana.mid', [ch])


def gen_T8():
    """T8 — მზე მიხვდა / Mze Mikhvda — D minor→major, ♩=50"""
    tempo = bpm_to_tempo(50)
    ch = make_track('Chuniri+Mezzo (T8)', 0, VIOLIN,
        ['A4','C5','B4','A4','G4','F4','E4','D4',
         'F4','A4','C5','B4','A4','G4','F4','E4','D4'],
        tempo, velocity=72, note_dur=H)
    save_midi('T08_Mze_Mikhvda.mid', [ch])


def gen_T9():
    """T9 — ოდოია / Odoia — D aeolian, ♩=70"""
    tempo = bpm_to_tempo(70)
    ch = make_track('Chuniri (T9)', 0, VIOLIN,
        ['D4','F4','E4','D4','C4','D4',
         'R',
         'F4','G4','A4','G4','F4','E4','D4',
         'R',
         'A4','C5','B4','A4','G4','F4','E4','D4'],
        tempo, velocity=68)
    wc = make_track('Women Choir (T9)', 1, CHOIR_AAH,
        ['D4','F4','E4','D4','C4','D4',
         'R',
         'F4','G4','A4','G4','F4','E4','D4',
         'R',
         'A4','C5','B4','A4','G4','F4','E4','D4'],
        tempo, velocity=62)
    save_midi('T09_Odoia.mid', [ch, wc])


def gen_T10():
    """T10 — სამკურაო / Samkurao — D minor, ♩=46"""
    tempo = bpm_to_tempo(46)
    ch = make_track('Chuniri (T10)', 0, VIOLIN,
        ['D4','F4','E4','D4','C4','D4',
         'R',
         'F4','G4','A4','G4','F4','E4','D4',
         'R',
         'A4','C5','B4','A4','G4','F4','E4','D4','C4','D4'],
        tempo, velocity=65, note_dur=H)
    ms = make_track('Mezzo-soprano (T10)', 1, VOICE_OOH,
        ['D4','F4','E4','D4','C4','D4',
         'R',
         'F4','G4','A4','G4','F4','E4','D4',
         'R',
         'A4','C5','B4','A4','G4','F4','E4','D4','C4','D4'],
        tempo, velocity=70, note_dur=H)
    save_midi('T10_Samkurao.mid', [ch, ms])


def gen_T11():
    """T11 — ლილე (ფინ.) / Lile Finale — D major, ♩=96"""
    tempo = bpm_to_tempo(96)
    s1 = make_track('Soprano I (T11)', 0, CHOIR_AAH,
        ['D5','F5','E5','D5','C5','D5','F5','G5','A5','G5','F5','E5','D5'],
        tempo, velocity=82)
    s2 = make_track('Soprano II (T11)', 1, CHOIR_AAH,
        ['A4','C5','B4','A4','G4','A4','C5','D5','E5','D5','C5','B4','A4'],
        tempo, velocity=78)
    al = make_track('Alto (T11)', 2, CHOIR_AAH,
        ['D4','F4','E4','D4','C4','D4','F4','G4','A4','G4','F4','E4','D4'],
        tempo, velocity=74)
    save_midi('T11_Lile.mid', [s1, s2, al])


def gen_T12():
    """T12 — მთიულური / Mtiuluri — A major, 5/8, ♩.=60"""
    tempo = bpm_to_tempo(60)
    pd = make_track('Panduri+Soprano (T12)', 0, GUITAR,
        ['A4','B4','C5','B4','A4','G4','A4','B4','C5','A4',
         'C5','D5','E5','D5','C5','B4','C5','D5','E5','C5'],
        tempo, velocity=82, note_dur=T3_8)
    save_midi('T12_Mtiuluri.mid', [pd])


def gen_T13():
    """T13 — განდაგანა / Gandagana — A major vs A minor, rubato"""
    tempo = bpm_to_tempo(54)
    sh = make_track('Shamhat (T13)', 0, CHOIR_AAH,
        ['A4','C5','B4','A4','G4','A4','B4','C5','A4'],
        tempo, velocity=78)
    en = make_track('Enkidu (T13)', 1, VOICE_OOH,
        ['A4','G4','E4','D4','C4','R','D4','E4','G4','A4'],
        tempo, velocity=68)
    save_midi('T13_Gandagana.mid', [sh, en])


def gen_T14():
    """T14 — შამხ. წყ. / Shamhat's Curse — A minor, free (a cappella)"""
    tempo = bpm_to_tempo(55)
    sp = make_track('Soprano a cappella (T14)', 0, CHOIR_AAH,
        ['A4','G4','F4','E4','D4','C4','D4','E4','F4','G4','A4',
         'G4','A4','B4','C5','B4','A4','G4','F4','E4','D4',
         'A5','H','G5','F5','E5','D5','C5','B4','A4'],
        tempo, velocity=88, note_dur=Q)
    save_midi('T14_Shamhat_Curse.mid', [sp])


def gen_T15():
    """T15 — ხასანბეგ. / Khasanbegura — D minor, 5/8, ♩.=66"""
    tempo = bpm_to_tempo(66)
    oc = make_track('Orchestra (T15)', 0, STRINGS,
        ['D4','F#4','A4','D5','C5','B4','A4','G4','F#4','E4','D4'],
        tempo, velocity=88, note_dur=T3_8)
    save_midi('T15_Khasanbegura.mid', [oc])


def gen_T16():
    """T16 — ბ-ბ. / Beri-Berikoba — G minor, syncopated"""
    tempo = bpm_to_tempo(58)
    ch = make_track('Choir SATB (T16)', 0, CHOIR_AAH,
        ['G4','B4','D5','C5','B4','A4','G4','F#4','G4'],
        tempo, velocity=80)
    save_midi('T16_Beri_Berikoba.mid', [ch])


def gen_T17():
    """T17 — მრავ. / Mravalzhamier — G major, ♩=72"""
    tempo = bpm_to_tempo(72)
    ch = make_track('Choir+Orchestra (T17)', 0, CHOIR_AAH,
        ['G4','B4','D5','G5','F#5','E5','D5','C5','B4','A4','G4'],
        tempo, velocity=85)
    save_midi('T17_Mravalzhamier.mid', [ch])


def gen_T18():
    """T18 — რეხ. / Rekhviashi — D minor, ♩=66"""
    tempo = bpm_to_tempo(66)
    mc = make_track("Men's Choir (T18)", 0, CHOIR_AAH,
        ['D4','E4','G4','A4','C5','A4','G4','E4','D4'],
        tempo, velocity=82)
    save_midi('T18_Rekhviashi.mid', [mc])


def gen_T19():
    """T19 — ხუმ. / Humbaba — C# minor chromatic, ♩=40"""
    tempo = bpm_to_tempo(40)
    bp = make_track('Bass-profundo (T19)', 0, VOICE_OOH,
        ['D4','Db4','C4','B3','Bb3','A3','Ab3','G3','F#3','F3','E3','Eb3','D3'],
        tempo, velocity=80, note_dur=H)
    # off-stage canon — same theme, delayed, quieter
    ca = make_track('Tree Chorus canon (T19)', 1, CHOIR_AAH,
        ['R','R',  # 2-beat delay
         'D4','Db4','C4','B3','Bb3','A3','Ab3','G3','F#3','F3','E3','Eb3','D3'],
        tempo, velocity=48, note_dur=H)
    save_midi('T19_Humbaba.mid', [bp, ca])


def gen_T20():
    """T20 — ჩ. (ო.) / Chakrulo Orchestral — B♭ major, 7/8, ♩=120"""
    tempo = bpm_to_tempo(120)
    br = make_track('Brass (T20)', 0, BRASS,
        ['Bb4','C5','D5','Eb5','F5','G5','F5','Eb5','D5','C5','Bb4'],
        tempo, velocity=100, note_dur=E)
    st = make_track('Strings (T20)', 1, STRINGS,
        ['Bb4','C5','D5','Eb5','F5','G5','F5','Eb5','D5','C5','Bb4'],
        tempo, velocity=88, note_dur=E)
    save_midi('T20_Chakrulo.mid', [br, st])


# ═══════════════════════════════════════════════════════════════════════════════
# FULL OPERA PREVIEW — все темы в порядке сцен
# ═══════════════════════════════════════════════════════════════════════════════

SCENE_ORDER = [
    # (scene_label, theme_fn, tempo_bpm, channel, instrument, notes, note_dur)
    # Act I
    ("Sc.1 — Урук (T16)",    bpm_to_tempo(58), 0, CHOIR_AAH,
     ['G4','B4','D5','C5','B4','A4','G4','F#4','G4'], Q),
    ("Sc.1 — Трио T1",       bpm_to_tempo(72), 1, VOICE_OOH,
     ['A4','D5','F#5','E5','D5','C#5','D4','B3','A4'], Q),
    ("Sc.2 — Нана T7",       bpm_to_tempo(60), 0, VIOLIN,
     ['D4','F4','E4','D4','C4','D4','F4','G4','A4','G4','F4','E4','D4'], Q),
    ("Sc.2 — Трио T1 ff",    bpm_to_tempo(72), 1, CHOIR_AAH,
     ['D5','F#5','A5','G5','F#5','E5','D5','C#5','D5'], Q),
    ("Sc.3 — Зари T4",       bpm_to_tempo(52), 0, PAN_FLUTE,
     ['D4','E4','G4','A4','G4','E4','D4','R','G4','A4','C5','D5','C5','A4','G4'], H),
    # Act II
    ("Sc.4 — Mtiuluri T12",  bpm_to_tempo(60), 0, GUITAR,
     ['A4','B4','C5','B4','A4','G4','A4','B4','C5','A4'], T3_8),
    ("Sc.4 — Gandagana T13", bpm_to_tempo(54), 0, CHOIR_AAH,
     ['A4','C5','B4','A4','G4','A4','B4','C5','A4'], Q),
    ("Sc.6 — Khasanbeg T15", bpm_to_tempo(66), 0, STRINGS,
     ['D4','F#4','A4','D5','C5','B4','A4','G4','F#4','E4','D4'], T3_8),
    ("Sc.7 — Rekhv T18",     bpm_to_tempo(66), 0, CHOIR_AAH,
     ['D4','E4','G4','A4','C5','A4','G4','E4','D4'], Q),
    ("Sc.7 — Mravalzh T17",  bpm_to_tempo(72), 0, CHOIR_AAH,
     ['G4','B4','D5','G5','F#5','E5','D5','C5','B4','A4','G4'], Q),
    # Act III
    ("Sc.8 — Odoia T9",      bpm_to_tempo(70), 0, VIOLIN,
     ['D4','F4','E4','D4','C4','D4','R','F4','G4','A4','G4','F4','E4','D4','R','A4','C5','B4','A4','G4','F4','E4','D4'], Q),
    ("Sc.8 — Samkurao T10",  bpm_to_tempo(46), 0, VIOLIN,
     ['D4','F4','E4','D4','C4','D4','R','F4','G4','A4','G4','F4','E4','D4','R','A4','C5','B4','A4','G4','F4','E4','D4','C4','D4'], H),
    ("Sc.9 — March T18",     bpm_to_tempo(66), 0, CHOIR_AAH,
     ['D4','E4','G4','A4','C5','A4','G4','E4','D4'], Q),
    ("Sc.10 — Humbaba T19",  bpm_to_tempo(40), 0, VOICE_OOH,
     ['D4','Db4','C4','B3','Bb3','A3','Ab3','G3','F#3','F3','E3','Eb3','D3'], H),
    # Act IV
    ("Sc.11 — Chakrulo T20", bpm_to_tempo(120), 0, BRASS,
     ['Bb4','C5','D5','Eb5','F5','G5','F5','Eb5','D5','C5','Bb4'], E),
    ("Sc.11 — Mravalzh T17 ff", bpm_to_tempo(72), 0, CHOIR_AAH,
     ['G4','B4','D5','G5','F#5','E5','D5','C5','B4','A4','G4'], Q),
    ("Sc.12 — Curse T14",    bpm_to_tempo(55), 0, CHOIR_AAH,
     ['A4','G4','F4','E4','D4','C4','D4','E4','F4','G4','A4',
      'G4','A4','B4','C5','B4','A4','G4','F4','E4','D4',
      'A5','H','G5','F5','E5','D5','C5','B4','A4'], Q),
    ("Sc.13 — Virishkhau T6", bpm_to_tempo(40), 0, PAN_FLUTE,
     ['D4','H','E4','H','G4','H','A4','G4','E4','D4'], H),
    ("Sc.13 — Samkurao T10", bpm_to_tempo(46), 0, VIOLIN,
     ['D4','F4','E4','D4','C4','D4','R','F4','G4','A4','G4','F4','E4','D4','R','A4','C5','B4','A4'], H),
    ("Sc.13 — Trio T2 dis",  bpm_to_tempo(88), 0, CHOIR_AAH,
     ['C#5','G5','A5','F5','B5','D#5','G#5','E5','F5'], Q),
    # Act V
    ("Sc.14 — Trio T2 fff",  bpm_to_tempo(88), 0, CHOIR_AAH,
     ['A4','G#4','G4','F#4','F4','E4','D#4','D4','C#4'], Q),
    ("Sc.15 — Death waters", bpm_to_tempo(40), 0, CELLO,
     ['E3','H','H','H','H'], W),   # E pedal
    ("Sc.16 — Utnapistim",   bpm_to_tempo(66), 0, STRINGS,
     ['G4','B4','D5','B4','G4','D5','B4','G4','D4','G4'], H),
    ("Sc.16 — Alilo T3 pp",  bpm_to_tempo(66), 0, CHOIR_AAH,
     ['A4','D5','F#5','E5','D5','C#5','D4','B3','A4','F#4','A4'], Q),
    ("Sc.17 — Alilo T3 ff",  bpm_to_tempo(66), 0, CHOIR_AAH,
     ['D5','F#5','A5','G5','F#5','E5','D5','C#5','D5','A4','D5'], Q),
    ("Sc.17 — Lile T11",     bpm_to_tempo(96), 0, CHOIR_AAH,
     ['D5','F5','E5','D5','C5','D5','F5','G5','A5','G5','F5','E5','D5'], Q),
    ("Sc.17 — Svan echo T4", bpm_to_tempo(52), 0, PAN_FLUTE,
     ['D4','E4','G4','R','D4','R','R','R'], H),  # pppp echo
    ("Sc.17 — Cello D final", bpm_to_tempo(40), 0, CELLO,
     ['D3','H','H','H','H','H'], W),   # D pedal → 0
]


def gen_full_preview():
    """Single MIDI track with all themes in scene order."""
    mid = MidiFile(type=0, ticks_per_beat=TPB)
    track = MidiTrack()
    mid.tracks.append(track)

    track.append(MetaMessage('track_name', name='SAMNU AZUZI -- Full Preview', time=0))

    for item in SCENE_ORDER:
        label, tempo, channel, instrument, notes, note_dur = item
        # scene marker
        safe_label = label.encode('ascii', 'replace').decode('ascii')
        track.append(MetaMessage('marker', text=safe_label, time=0))
        track.append(MetaMessage('set_tempo', tempo=tempo, time=0))
        track.append(Message('program_change', channel=0,
                              program=instrument, time=0))
        # silence between scenes (1 bar)
        track.append(Message('note_on', channel=0, note=0, velocity=0, time=0))
        track.append(Message('note_off', channel=0, note=0, velocity=0, time=Q*2))

        i = 0
        while i < len(notes):
            token = notes[i]
            if token == 'R':
                track.append(Message('note_on', channel=0, note=0, velocity=0, time=0))
                track.append(Message('note_off', channel=0, note=0, velocity=0, time=note_dur))
                i += 1
                continue
            if token == 'H':
                i += 1
                continue
            pitch = note_to_midi(token)
            if pitch is None:
                i += 1
                continue
            dur = note_dur
            j = i + 1
            while j < len(notes) and notes[j] == 'H':
                dur += W; j += 1
            vel = 75
            track.append(Message('note_on',  channel=0, note=pitch, velocity=vel, time=0))
            track.append(Message('note_off', channel=0, note=pitch, velocity=0,   time=dur))
            i = j

    path = os.path.join(OUTPUT_DIR, '00_SAMNU_AZUZI_Full_Preview.mid')
    mid.save(path)
    print(f"  ✓  00_SAMNU_AZUZI_Full_Preview.mid")


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    print("\n╔══════════════════════════════════════════════════╗")
    print("║  ŠAMNU AZUZI — MIDI Score Generator             ║")
    print("║  Опера Джабы Ткемаладзе                         ║")
    print("╚══════════════════════════════════════════════════╝\n")
    print("Генерирую темы T1–T20...\n")

    gen_T1();  gen_T2();  gen_T3();  gen_T4();  gen_T5()
    gen_T6();  gen_T7();  gen_T8();  gen_T9();  gen_T10()
    gen_T11(); gen_T12(); gen_T13(); gen_T14(); gen_T15()
    gen_T16(); gen_T17(); gen_T18(); gen_T19(); gen_T20()

    print("\nГенерирую полную превью-партитуру...\n")
    gen_full_preview()

    print(f"\n✅  Готово — {len(SCENE_ORDER)+20} файлов в {OUTPUT_DIR}/")
    print("\nПорядок актов в превью:")
    for item in SCENE_ORDER:
        print(f"  ▸ {item[0]}")


if __name__ == '__main__':
    main()
