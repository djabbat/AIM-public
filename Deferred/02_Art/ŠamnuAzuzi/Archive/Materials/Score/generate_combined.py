#!/usr/bin/env python3
"""
ŠAMNU AZUZI — COMPLETE SCORE
Overture (180 measures) + Acts I–V (1573 measures) = 1753 measures total
20 unified parts: 8 vocal + 12 instrumental

Music: Dr. Jaba Tkemaladze
"""

import os
import copy

from music21 import (
    stream, note, chord, meter, key, tempo, instrument,
    metadata, expressions, clef, bar
)

BASE = os.path.dirname(os.path.abspath(__file__))
OVERTURE_FILE = os.path.join(BASE, 'SAMNU_AZUZI_Overture.musicxml')
OPERA_FILE    = os.path.join(BASE, 'SAMNU_AZUZI_v3.musicxml')
OUT_FILE      = os.path.join(BASE, 'SAMNU_AZUZI_Complete.musicxml')

OV_MEASURES   = 180
OP_MEASURES   = 1573


# ══════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════

def get_measures(part):
    """Return a list of Measure objects from a Part."""
    return list(part.getElementsByClass('Measure'))


def get_part_by_name(score, name):
    """Find a part by partName (case-insensitive substring match)."""
    for p in score.parts:
        if p.partName and name.lower() in p.partName.lower():
            return p
    return None


def deep_copy_measures(measures_list):
    """Deep-copy a list of measure objects."""
    return [copy.deepcopy(m) for m in measures_list]


def make_rest_measures(count, ts_str='4/4'):
    """Create 'count' Measure objects filled with a single whole rest."""
    beats = int(ts_str.split('/')[0])
    denom = int(ts_str.split('/')[1])
    # Quarter length of the full measure
    quarter_length = beats * (4.0 / denom)
    measures = []
    for i in range(count):
        m = stream.Measure()
        m.timeSignature = meter.TimeSignature(ts_str)
        r = note.Rest()
        r.duration.quarterLength = quarter_length
        m.append(r)
        measures.append(m)
    return measures


def build_combined_part(name, inst_obj, ov_measures, op_measures,
                        ov_rehearsal_mark=True):
    """
    Create a new Part by concatenating overture measures then opera measures.
    ov_measures: list of Measure (180 items) — may be rests or real content
    op_measures: list of Measure (1573 items) — real content
    """
    p = stream.Part()
    p.partName = name
    p.id = name.replace(' ', '_').replace('/', '_')
    inst_obj.partName = name
    p.insert(0, inst_obj)

    for i, m in enumerate(ov_measures):
        mc = copy.deepcopy(m)
        # Ensure measure number is sequential from 1
        mc.number = i + 1
        # Add rehearsal mark at m.1
        if i == 0 and ov_rehearsal_mark:
            rm = expressions.RehearsalMark('OVERTURE')
            rm.style.fontSize = 14
            mc.insert(0, rm)
        p.append(mc)

    for j, m in enumerate(op_measures):
        mc = copy.deepcopy(m)
        mc.number = OV_MEASURES + j + 1
        # Add rehearsal mark at first opera measure
        if j == 0 and ov_rehearsal_mark:
            rm = expressions.RehearsalMark('ACT I')
            rm.style.fontSize = 14
            mc.insert(0, rm)
        p.append(mc)

    return p


def merge_brass_parts(ov_score, n_measures):
    """
    Merge Horn + Trumpet + Trombone overture parts into a single 'Brass' part.
    Uses Horn as primary; where Horn is rest, fills from Trumpet, then Trombone.
    """
    horn_p   = get_part_by_name(ov_score, 'Horn')
    trump_p  = get_part_by_name(ov_score, 'Trumpet')
    trombone_p = get_part_by_name(ov_score, 'Trombone')

    horn_ms   = get_measures(horn_p)   if horn_p   else []
    trump_ms  = get_measures(trump_p)  if trump_p  else []
    trombone_ms = get_measures(trombone_p) if trombone_p else []

    merged = []
    for i in range(n_measures):
        # Pick the measure with actual notes (not all rests)
        candidates = []
        for ms_list in [horn_ms, trump_ms, trombone_ms]:
            if i < len(ms_list):
                candidates.append(ms_list[i])
            else:
                candidates.append(None)

        chosen = None
        for c in candidates:
            if c is None:
                continue
            notes = list(c.flatten().notes)
            if notes:
                chosen = c
                break
        if chosen is None and candidates[0] is not None:
            chosen = candidates[0]
        if chosen is None:
            m = stream.Measure()
            m.timeSignature = meter.TimeSignature('4/4')
            r = note.Rest()
            r.duration.quarterLength = 4.0
            m.append(r)
            chosen = m
        merged.append(chosen)
    return merged


# ══════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════

def build_combined_score():
    print("Loading overture score...")
    from music21 import converter
    overture = converter.parse(OVERTURE_FILE)

    print("Loading opera score...")
    opera = converter.parse(OPERA_FILE)

    # Print part inventories for verification
    print("\nOverture parts:")
    for i, p in enumerate(overture.parts):
        n = len(get_measures(p))
        print(f"  [{i:2d}] {p.partName!r:20s} — {n} measures")

    print("\nOpera parts:")
    for i, p in enumerate(opera.parts):
        n = len(get_measures(p))
        print(f"  [{i:2d}] {p.partName!r:20s} — {n} measures")

    # ── Overture sources ──────────────────────────────────────────────
    ov_flute      = get_part_by_name(overture, 'Flute')
    ov_oboe       = get_part_by_name(overture, 'Oboe')
    ov_clarinet   = get_part_by_name(overture, 'Clarinet')
    ov_bassoon    = get_part_by_name(overture, 'Bassoon')
    ov_violin1    = get_part_by_name(overture, 'Violin_I')
    ov_violin2    = get_part_by_name(overture, 'Violin_II')
    ov_cello      = get_part_by_name(overture, 'Cello')
    ov_contrabass = get_part_by_name(overture, 'Contrabass')
    ov_harp       = get_part_by_name(overture, 'Harp')
    ov_timpani    = get_part_by_name(overture, 'Timpani')

    # ── Opera sources ─────────────────────────────────────────────────
    op_gilgamesh  = get_part_by_name(opera, 'Gilgamesh')
    op_enkidu     = get_part_by_name(opera, 'Enkidu')
    op_ninsun     = get_part_by_name(opera, 'Ninsun')
    op_shamhat    = get_part_by_name(opera, 'Shamhat')
    op_humbaba    = get_part_by_name(opera, 'Humbaba')
    op_mkrimani   = get_part_by_name(opera, 'Mkrimani')
    op_mtavari    = get_part_by_name(opera, 'Mtavari')
    op_bani       = get_part_by_name(opera, 'Bani')
    op_chorus     = get_part_by_name(opera, 'Chorus')
    op_lamuri     = get_part_by_name(opera, 'Lamuri')
    op_chuniri    = get_part_by_name(opera, 'Chuniri')
    op_panduri    = get_part_by_name(opera, 'Panduri')
    op_brass      = get_part_by_name(opera, 'Brass')
    op_cello      = get_part_by_name(opera, 'Cello')
    op_piano      = get_part_by_name(opera, 'Piano')
    op_strings    = get_part_by_name(opera, 'Strings')
    op_winds      = get_part_by_name(opera, 'Winds')

    # Fallbacks for missing parts
    def measures_or_rests(part, count, ts='4/4'):
        if part is not None:
            ms = get_measures(part)
            if len(ms) >= count:
                return ms[:count]
        return make_rest_measures(count, ts)

    # Get overture measures (default ts 4/4 for rests)
    ov_ms_flute      = measures_or_rests(ov_flute,      OV_MEASURES)
    ov_ms_violin1    = measures_or_rests(ov_violin1,    OV_MEASURES)
    ov_ms_violin2    = measures_or_rests(ov_violin2,    OV_MEASURES)
    ov_ms_cello      = measures_or_rests(ov_cello,      OV_MEASURES)
    ov_ms_contrabass = measures_or_rests(ov_contrabass, OV_MEASURES)
    ov_ms_harp       = measures_or_rests(ov_harp,       OV_MEASURES)
    ov_ms_timpani    = measures_or_rests(ov_timpani,    OV_MEASURES)
    ov_ms_oboe       = measures_or_rests(ov_oboe,       OV_MEASURES)
    ov_ms_clarinet   = measures_or_rests(ov_clarinet,   OV_MEASURES)
    ov_ms_bassoon    = measures_or_rests(ov_bassoon,    OV_MEASURES)

    # Brass: merge Horn+Trumpet+Trombone overture
    ov_ms_brass = merge_brass_parts(overture, OV_MEASURES)

    # Vocal rest measures (4/4 for overture)
    vocal_rests = make_rest_measures(OV_MEASURES, '4/4')

    # Get opera measures
    op_ms_gilgamesh  = measures_or_rests(op_gilgamesh,  OP_MEASURES)
    op_ms_enkidu     = measures_or_rests(op_enkidu,     OP_MEASURES)
    op_ms_ninsun     = measures_or_rests(op_ninsun,     OP_MEASURES)
    op_ms_shamhat    = measures_or_rests(op_shamhat,    OP_MEASURES)
    op_ms_humbaba    = measures_or_rests(op_humbaba,    OP_MEASURES)
    op_ms_mkrimani   = measures_or_rests(op_mkrimani,   OP_MEASURES)
    op_ms_mtavari    = measures_or_rests(op_mtavari,    OP_MEASURES)
    op_ms_bani       = measures_or_rests(op_bani,       OP_MEASURES)
    op_ms_chorus     = measures_or_rests(op_chorus,     OP_MEASURES)
    op_ms_lamuri     = measures_or_rests(op_lamuri,     OP_MEASURES)
    op_ms_chuniri    = measures_or_rests(op_chuniri,    OP_MEASURES)
    op_ms_panduri    = measures_or_rests(op_panduri,    OP_MEASURES)
    op_ms_brass      = measures_or_rests(op_brass,      OP_MEASURES)
    op_ms_cello      = measures_or_rests(op_cello,      OP_MEASURES)
    op_ms_piano      = measures_or_rests(op_piano,      OP_MEASURES)
    op_ms_strings    = measures_or_rests(op_strings,    OP_MEASURES)
    op_ms_winds      = measures_or_rests(op_winds,      OP_MEASURES)

    # ── Build combined score ──────────────────────────────────────────
    combined = stream.Score()
    md = metadata.Metadata()
    md.title    = 'Šamnu Azuzi — Complete Score (Overture + Acts I–V)'
    md.composer = 'Dr. Jaba Tkemaladze'
    combined.insert(0, md)

    # ── 20 unified parts in order ─────────────────────────────────────
    # Rehearsal marks only on the first part to avoid duplication in export
    first_part = True

    def add_part(name, inst_obj, ov_ms, op_ms):
        nonlocal first_part
        p = build_combined_part(name, inst_obj, ov_ms, op_ms,
                                ov_rehearsal_mark=first_part)
        combined.append(p)
        first_part = False

    print("\nBuilding combined score parts...")

    # 1. Gilgamesh (Baritone) — rests during overture
    add_part('Gilgamesh',          instrument.Baritone(),          vocal_rests, op_ms_gilgamesh)

    # 2. Enkidu (Tenor) — rests during overture
    add_part('Enkidu',             instrument.Tenor(),             vocal_rests, op_ms_enkidu)

    # 3. Ninsun (MezzoSoprano) — rests during overture
    add_part('Ninsun',             instrument.MezzoSoprano(),      vocal_rests, op_ms_ninsun)

    # 4. Shamhat (Soprano) — rests during overture
    add_part('Shamhat',            instrument.Soprano(),           vocal_rests, op_ms_shamhat)

    # 5. Humbaba/Utnapishtim (Bass) — rests during overture
    add_part('Humbaba/Utnapishti', instrument.Bass(),              vocal_rests, op_ms_humbaba)

    # 6. Mkrimani (Soprano) — rests during overture
    add_part('Mkrimani',           instrument.Soprano(),           vocal_rests, op_ms_mkrimani)

    # 7. Mtavari (Tenor) — rests during overture
    add_part('Mtavari',            instrument.Tenor(),             vocal_rests, op_ms_mtavari)

    # 8. Bani (Bass) — rests during overture
    add_part('Bani',               instrument.Bass(),              vocal_rests, op_ms_bani)

    # 9. Chorus (Choir) — rests during overture
    add_part('Chorus',             instrument.Choir(),             vocal_rests, op_ms_chorus)

    # 10. Flute/Lamuri — overture Flute + opera Lamuri
    add_part('Flute/Lamuri',       instrument.Flute(),             ov_ms_flute,      op_ms_lamuri)

    # 11. Chuniri/Violin I — overture Violin I + opera Chuniri
    add_part('Chuniri/Violin I',   instrument.Violin(),            ov_ms_violin1,    op_ms_chuniri)

    # 12. Panduri/Violin II — overture Violin II + opera Panduri
    add_part('Panduri/Violin II',  instrument.Violin(),            ov_ms_violin2,    op_ms_panduri)

    # 13. Piano/Harp — overture Harp + opera Piano
    add_part('Piano/Harp',         instrument.Piano(),             ov_ms_harp,       op_ms_piano)

    # 14. Cello — overture Cello + opera Cello
    add_part('Cello',              instrument.Violoncello(),       ov_ms_cello,      op_ms_cello)

    # 15. Contrabass — overture Contrabass + opera Strings (Contrabass role)
    add_part('Contrabass',         instrument.Contrabass(),        ov_ms_contrabass, op_ms_strings)

    # 16. Oboe/English Horn — overture Oboe; rests in opera (use Winds if available)
    op_ms_oboe_part = op_ms_winds if op_winds is not None else make_rest_measures(OP_MEASURES, '4/4')
    add_part('Oboe/English Horn',  instrument.Oboe(),              ov_ms_oboe,       op_ms_oboe_part)

    # 17. Clarinet — overture Clarinet; rests in opera
    add_part('Clarinet',           instrument.Clarinet(),          ov_ms_clarinet,   make_rest_measures(OP_MEASURES, '4/4'))

    # 18. Bassoon — overture Bassoon; rests in opera
    add_part('Bassoon',            instrument.Bassoon(),           ov_ms_bassoon,    make_rest_measures(OP_MEASURES, '4/4'))

    # 19. Brass (Horn+Trumpet+Trombone) — overture merged brass + opera Brass
    add_part('Brass',              instrument.Horn(),              ov_ms_brass,      op_ms_brass)

    # 20. Timpani — overture Timpani; minimal in opera (rests)
    add_part('Timpani',            instrument.Timpani(),           ov_ms_timpani,    make_rest_measures(OP_MEASURES, '4/4'))

    return combined


# ══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ══════════════════════════════════════════════════════════════════════

if __name__ == '__main__':
    print("=" * 60)
    print("ŠAMNU AZUZI — Complete Score Generator")
    print(f"Output: {OUT_FILE}")
    print("=" * 60)

    combined = build_combined_score()

    print("\nWriting MusicXML...")
    combined.write('musicxml', fp=OUT_FILE)

    size = os.path.getsize(OUT_FILE)
    print(f"\nDone. File size: {size:,} bytes ({size / (1024*1024):.1f} MB)")
    print(f"Output: {OUT_FILE}")

    # Verify part count and measure counts
    print("\nVerification:")
    for p in combined.parts:
        ms = list(p.getElementsByClass('Measure'))
        print(f"  {p.partName!r:25s} — {len(ms):5d} measures")
