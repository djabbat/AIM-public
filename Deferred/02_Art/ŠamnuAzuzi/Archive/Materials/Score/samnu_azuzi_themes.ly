\version "2.24.0"

%% ╔══════════════════════════════════════════════════════════════════╗
%% ║  ŠAMNU AZUZI — Тематический каталог / Thematic Catalogue       ║
%% ║  Опера в пяти актах                                            ║
%% ║  Автор: Джаба Ткемаладзе / Jaba Tkemaladze                     ║
%% ║  20 тем (T1–T20) — нотные эскизы                              ║
%% ╚══════════════════════════════════════════════════════════════════╝

\header {
  title = "ŠAMNU AZUZI"
  subtitle = "Тематический каталог / Thematic Catalogue"
  subsubtitle = "Темы T1–T20 · Опера в пяти актах"
  composer = "Джаба Ткемаладзе / Jaba Tkemaladze"
  poet = "Либретто / Libretto: Acts I–V (Georgian)"
  copyright = "© 2026 Jaba Tkemaladze"
  tagline = ##f
}

%% ─────────────────────────────────────────────────────────────────
%% T1 — წინწყარო (ჰარმ.) / TSINTSKARO (HARMONY)
%% Трио Гильгамеша — целостность · D major · ♩=72
%% ─────────────────────────────────────────────────────────────────

tOneMkrimani = \relative c'' {
  \key d \major
  \time 4/4
  \tempo "Andante moderato" 4 = 72
  d4 fis a g | fis e d cis | d2. r4 |
}

tOneMtavari = \relative c' {
  \key d \major
  \time 4/4
  a4 d fis e | d cis d b | a2. r4 |
}

tOneBani = \relative c {
  \key d \major
  \time 4/4
  d4 a d a | d a d a | d2. r4 |
}

%% ─────────────────────────────────────────────────────────────────
%% T2 — წინწყარო (დის.) / TSINTSKARO (DISSONANCE)
%% Трио Гильгамеша — распад · Atonal · ♩=88
%% ─────────────────────────────────────────────────────────────────

tTwoMkrimani = \relative c'' {
  \time 4/4
  \tempo "Agitato" 4 = 88
  cis4 g' a f | b dis gis e | f2. r4 |
}

tTwoMtavari = \relative c' {
  \time 4/4
  a4 gis g fis | f e dis d | cis2. r4 |
}

tTwoBani = \relative c {
  \time 4/4
  d2 ~ d4 ~ d8 ees | d2. r4 |
}

%% ─────────────────────────────────────────────────────────────────
%% T3 — ალილო / ALILO
%% Трио — финал · D major · ♩=66
%% ─────────────────────────────────────────────────────────────────

tThreeMkrimani = \relative c'' {
  \key d \major
  \time 4/4
  \tempo "Andante tranquillo" 4 = 66
  d4 fis a g | fis e d cis | d a' d,2 | r1 |
}

tThreeMtavari = \relative c' {
  \key d \major
  \time 4/4
  a4 d fis e | d cis d b | a fis a2 | r1 |
}

tThreeBani = \relative c {
  \key d \major
  \time 4/4
  d4 a' d a | d, a' d a | d, d' d,2 | r1 |
}

%% ─────────────────────────────────────────────────────────────────
%% T4 — ზარი (სუფთა) / ZARI (PURE)
%% Энкиду — Ламури · A minor · senza misura
%% ─────────────────────────────────────────────────────────────────

tFour = \relative c' {
  \key a \minor
  \time 4/4
  \tempo "Senza misura, rubato"
  \override Score.SpacingSpanner.base-shortest-duration = #(ly:make-moment 1/8)
  d2( e4 g) | a2( g4 e) | d1 | r2 |
  g2( a4 c) | d2( c4 a) | g1 |
}

%% ─────────────────────────────────────────────────────────────────
%% T5 — ზარი (ტრ.) / ZARI (TRANSFORMATION)
%% Энкиду + Шамхат · A minor → A major
%% ─────────────────────────────────────────────────────────────────

tFiveLamuri = \relative c' {
  \key a \minor
  \time 4/4
  \tempo "Moderato" 4 = 80
  d4 e g a | b a g fis | e d2. |
}

tFivePanduri = \relative c' {
  \key a \major
  \time 4/4
  a4 b c d | e d c b | a g a2 |
}

%% ─────────────────────────────────────────────────────────────────
%% T6 — ვირიშხაუ / VIRISHKHAU
%% Смерть Энкиду · D minor · ♩=40
%% ─────────────────────────────────────────────────────────────────

tSixLamuri = \relative c' {
  \key d \minor
  \time 4/4
  \tempo "Lento molto rubato" 4 = 40
  \dynamicDown
  d1\p ~ | d4( e1) ~ | e4( g1) ~ | g4( a4 g e) | d1\ppp |
}

tSixEnkidu = \relative c' {
  \key d \minor
  \time 4/4
  a2\p( g4 e) | d2( c4 a) | a1\ppp | r1 |
}

%% ─────────────────────────────────────────────────────────────────
%% T7 — ნანა (იავნანა) / NANA (LULLABY)
%% Нинсун · D minor · ♩=60
%% ─────────────────────────────────────────────────────────────────

tSeven = \relative c' {
  \key d \minor
  \time 3/4
  \tempo "Andante dolce" 4 = 60
  d4( f e) | d( c d) | f( g a) | g( f e) | d2. |
}

%% ─────────────────────────────────────────────────────────────────
%% T8 — მზე მიხვდა / MZE MIKHVDA
%% Нинсун — пророчество · D minor→major · ♩=50
%% ─────────────────────────────────────────────────────────────────

tEight = \relative c' {
  \key d \minor
  \time 4/4
  \tempo "Largo maestoso" 4 = 50
  a'2( c4 b) | a2( g4 f) | e d f a | c b a2 |
  \key d \major
  f4 a d2 | c4 b a2 | g4 f e d | d1\fermata |
}

%% ─────────────────────────────────────────────────────────────────
%% T9 — ოდოია / ODOIA
%% Нинсун — ритуал · D aeolian · ♩=70
%% ─────────────────────────────────────────────────────────────────

tNine = \relative c' {
  \key d \dorian
  \time 4/4
  \tempo "Moderato religioso" 4 = 70
  d4 f e d | c d2 r4 |
  f4 g a g | f e d2 | r2 |
  a'4 c b a | g f e d |
}

%% ─────────────────────────────────────────────────────────────────
%% T10 — სამკურაო / SAMKURAO
%% Нинсун — плач · D minor · ♩=46
%% ─────────────────────────────────────────────────────────────────

tTen = \relative c' {
  \key d \minor
  \time 4/4
  \tempo "Lento doloroso" 4 = 46
  d2( f4 e) | d2( c4 d) | r2 |
  f4( g a g) | f e d2 | r2 |
  a'2( c4 b) | a g f e | d c d1\fermata |
}

%% ─────────────────────────────────────────────────────────────────
%% T11 — ლილე (ფინ.) / LILE (FINALE)
%% Нинсун + женщины · D major · ♩=96
%% ─────────────────────────────────────────────────────────────────

tElevenSopI = \relative c'' {
  \key d \major
  \time 4/4
  \tempo "Allegro moderato" 4 = 96
  d4 f e d | c d f g | a g f e | d2. r4 |
}

tElevenSopII = \relative c' {
  \key d \major
  \time 4/4
  a4 c b a | g a c d | e d c b | a2. r4 |
}

tElevenAlto = \relative c' {
  \key d \major
  \time 4/4
  d4 f e d | c d f g | a g f e | d2. r4 |
}

%% ─────────────────────────────────────────────────────────────────
%% T12 — მთიულური / MTIULURI
%% Шамхат · A major · 5/8 · ♩.=60
%% ─────────────────────────────────────────────────────────────────

tTwelve = \relative c' {
  \key a \major
  \time 5/8
  \tempo "Allegro con fuoco" 4. = 60
  a8[ b c b a] | g[ a b c a] |
  c[ d e d c] | b[ c d e c] |
}

%% ─────────────────────────────────────────────────────────────────
%% T13 — განდაგანა / GANDAGANA
%% Шамхат + Энкиду · A major vs A minor
%% ─────────────────────────────────────────────────────────────────

tThirteenShamhat = \relative c' {
  \key a \major
  \time 4/4
  \tempo "Moderato, rubato" 4. = 54
  a'4( c b a) | g( a b c) | a2. r4 |
}

tThirteenEnkidu = \relative c' {
  \key a \minor
  \time 4/4
  a4( g e d) | c2 r2 | d4( e g a) |
}

%% ─────────────────────────────────────────────────────────────────
%% T14 — შამხ. წყ. / SHAMHAT'S CURSE
%% Сопрано a cappella · A minor · libero
%% ─────────────────────────────────────────────────────────────────

tFourteen = \relative c' {
  \key a \minor
  \time 4/4
  \tempo "Libero, con passione"
  a4\p( g f e) | d( c d e) | f( g a2) |
  g4( a b c) | b( a g f) | e d2.\< |
  a''1\ff ~ | a4\> g f e | d c b a\ppp\fermata |
}

%% ─────────────────────────────────────────────────────────────────
%% T15 — ხასანბეგ. / KHASANBEGURA
%% Боевая тема · D minor · 5/8 · ♩.=66
%% ─────────────────────────────────────────────────────────────────

tFifteen = \relative c' {
  \key d \minor
  \time 5/8
  \tempo "Allegro marziale" 4. = 66
  d8[ fis a d c] | b[ a g fis e] | d4. r4 |
}

%% ─────────────────────────────────────────────────────────────────
%% T16 — ბ-ბ. / BERI-BERIKOBA
%% Хор горожан · G minor · синкопа
%% ─────────────────────────────────────────────────────────────────

tSixteen = \relative c' {
  \key g \minor
  \time 5/8
  \tempo "Allegro giocoso" 4. = 58
  g8[ bes d c bes] | a[ g fis g r8] |
}

%% ─────────────────────────────────────────────────────────────────
%% T17 — მრავალჟამიერ / MRAVALZHAMIER
%% Торжество · G major · ♩=72
%% ─────────────────────────────────────────────────────────────────

tSeventeen = \relative c' {
  \key g \major
  \time 4/4
  \tempo "Andante festivo" 4 = 72
  g4\f( b d g) | fis( e d c) | b( a g2) |
}

%% ─────────────────────────────────────────────────────────────────
%% T18 — რეხვიაში / REKHVIASHI
%% Мужской хор · D minor · ♩=66
%% ─────────────────────────────────────────────────────────────────

tEighteen = \relative c' {
  \key d \minor
  \time 4/4
  \tempo "Moderato pesante" 4 = 66
  d4\mf( e g a) | c( a g e) | d2. r4 |
}

%% ─────────────────────────────────────────────────────────────────
%% T19 — ხუმბაბას თ. / HUMBABA'S THEME
%% Хроматический спуск · C# minor · ♩=40
%% ─────────────────────────────────────────────────────────────────

tNineteen = \relative c' {
  \time 4/4
  \tempo "Lento lugubre" 4 = 40
  d2\mf( des4 c) | b2( bes4 a) | aes2( g4 fis) | f2( e4 ees) | d1\pp\fermata |
}

%% ─────────────────────────────────────────────────────────────────
%% T20 — ჩაკრულო (ო.) / CHAKRULO (ORCHESTRAL)
%% Ложный триумф · B♭ major · 7/8 · ♩=120
%% ─────────────────────────────────────────────────────────────────

tTwenty = \relative c' {
  \key bes \major
  \time 7/8
  \tempo "Allegro eroico" 4 = 120
  bes8\ff[ c d ees f g f] | ees[ d c bes4.] |
}


%% ═══════════════════════════════════════════════════════════════════
%% ВЁРСТКА / LAYOUT
%% ═══════════════════════════════════════════════════════════════════

\book {

  %% ── T1 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T1 — წინწყარო (ჰარმ.) / Tsintskaro (Harmony)" }
    \score {
      \new StaffGroup <<
        \new Staff \with { instrumentName = "Мкримани" }
          \tOneMkrimani
        \new Staff \with { instrumentName = "Мтавари" }
          \tOneMtavari
        \new Staff \with { instrumentName = "Бани" }
          \clef bass \tOneBani
      >>
      \layout {}
      \midi {}
    }
  }

  %% ── T2 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T2 — წინწყარო (დის.) / Tsintskaro (Dissonance)" }
    \score {
      \new StaffGroup <<
        \new Staff \with { instrumentName = "Мкримани" }
          \tTwoMkrimani
        \new Staff \with { instrumentName = "Мтавари" }
          \tTwoMtavari
        \new Staff \with { instrumentName = "Бани" }
          \clef bass \tTwoBani
      >>
      \layout {}
      \midi {}
    }
  }

  %% ── T3 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T3 — ალილო / Alilo" }
    \score {
      \new StaffGroup <<
        \new Staff \with { instrumentName = "Мкримани" }
          \tThreeMkrimani
        \new Staff \with { instrumentName = "Мтавари" }
          \tThreeMtavari
        \new Staff \with { instrumentName = "Бани" }
          \clef bass \tThreeBani
      >>
      \layout {}
      \midi {}
    }
  }

  %% ── T4 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T4 — ზარი (სუფთა) / Zari (Pure) — Ламури" }
    \score {
      \new Staff \with { instrumentName = "Ламури" }
        \tFour
      \layout {}
      \midi {}
    }
  }

  %% ── T5 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T5 — ზარი (ტრ.) / Zari (Transformation)" }
    \score {
      \new StaffGroup <<
        \new Staff \with { instrumentName = "Ламури" }
          \tFiveLamuri
        \new Staff \with { instrumentName = "Пандури" }
          \tFivePanduri
      >>
      \layout {}
      \midi {}
    }
  }

  %% ── T6 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T6 — ვირიშხაუ / Virishkhau — Смерть Энкиду" }
    \score {
      \new StaffGroup <<
        \new Staff \with { instrumentName = "Ламури" }
          \tSixLamuri
        \new Staff \with { instrumentName = "Энкиду (тенор)" }
          \tSixEnkidu
      >>
      \layout {}
      \midi {}
    }
  }

  %% ── T7 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T7 — ნანა / Nana — Нинсун, колыбельная" }
    \score {
      \new Staff \with { instrumentName = "Чунири/Меццо" }
        \tSeven
      \layout {}
      \midi {}
    }
  }

  %% ── T8 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T8 — მზე მიხვდა / Mze Mikhvda — пророчество" }
    \score {
      \new Staff \with { instrumentName = "Чунири/Меццо" }
        \tEight
      \layout {}
      \midi {}
    }
  }

  %% ── T9 ─────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T9 — ოდოია / Odoia — Нинсун, ритуал" }
    \score {
      \new Staff \with { instrumentName = "Чунири+Хор" }
        \tNine
      \layout {}
      \midi {}
    }
  }

  %% ── T10 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T10 — სამკურაო / Samkurao — Нинсун, плач" }
    \score {
      \new Staff \with { instrumentName = "Чунири/Меццо" }
        \tTen
      \layout {}
      \midi {}
    }
  }

  %% ── T11 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T11 — ლილე / Lile — финал, женский хор" }
    \score {
      \new ChoirStaff <<
        \new Staff \with { instrumentName = "Сопр. I" }
          \tElevenSopI
        \new Staff \with { instrumentName = "Сопр. II" }
          \tElevenSopII
        \new Staff \with { instrumentName = "Альт" }
          \tElevenAlto
      >>
      \layout {}
      \midi {}
    }
  }

  %% ── T12 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T12 — მთიულური / Mtiuluri — Шамхат, 5/8" }
    \score {
      \new Staff \with { instrumentName = "Пандури/Сопр." }
        \tTwelve
      \layout {}
      \midi {}
    }
  }

  %% ── T13 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T13 — განდაგანა / Gandagana — дуэт Шамхат+Энкиду" }
    \score {
      \new StaffGroup <<
        \new Staff \with { instrumentName = "Шамхат (А major)" }
          \tThirteenShamhat
        \new Staff \with { instrumentName = "Энкиду (A minor)" }
          \tThirteenEnkidu
      >>
      \layout {}
      \midi {}
    }
  }

  %% ── T14 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T14 — Shamhat's Curse — сопрано a cappella" }
    \score {
      \new Staff \with { instrumentName = "Шамхат (сопрано)" }
        \tFourteen
      \layout {}
      \midi {}
    }
  }

  %% ── T15 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T15 — ხასანბეგ. / Khasanbegura — 5/8 боевая" }
    \score {
      \new Staff \with { instrumentName = "Оркестр" }
        \tFifteen
      \layout {}
      \midi {}
    }
  }

  %% ── T16 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T16 — ბ-ბ. / Beri-Berikoba — хор горожан" }
    \score {
      \new Staff \with { instrumentName = "Хор SATB" }
        \tSixteen
      \layout {}
      \midi {}
    }
  }

  %% ── T17 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T17 — მრავ. / Mravalzhamier — торжество" }
    \score {
      \new Staff \with { instrumentName = "Хор+Оркестр" }
        \tSeventeen
      \layout {}
      \midi {}
    }
  }

  %% ── T18 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T18 — რეხვ. / Rekhviashi — мужской хор" }
    \score {
      \new Staff \with { instrumentName = "Муж. хор TTB" }
        \tEighteen
      \layout {}
      \midi {}
    }
  }

  %% ── T19 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T19 — Humbaba — хроматический спуск" }
    \score {
      \new Staff \with { instrumentName = "Бас-профундо" \clef bass }
        \tNineteen
      \layout {}
      \midi {}
    }
  }

  %% ── T20 ────────────────────────────────────────────────────────
  \bookpart {
    \header { piece = "T20 — ჩაკრ. / Chakrulo — 7/8 ложный триумф" }
    \score {
      \new Staff \with { instrumentName = "Оркестр (брасс)" }
        \tTwenty
      \layout {}
      \midi {}
    }
  }

} %% end \book
