#!/usr/bin/env python3
"""
AIM — Literature Monitor
Ежедневный сбор научных новостей и статей по темам проектов Dr. Jaba.
Запускается 4 раза в день: 09:00, 12:00, 15:00, 18:00.
Ищет в PubMed (eutils), Europe PMC, bioRxiv/medRxiv (CrossRef), Semantic Scholar.
Аннотации на русском через DeepSeek.
Результаты: ~/Desktop/AIM/literature_digest/YYYY-MM-DD_HH.md
"""

import os
import sys
import json
import datetime
import urllib.request
import urllib.parse
import urllib.error
import time

sys.path.insert(0, os.path.dirname(__file__))
from llm import ask_llm, MODEL_FAST

# ── Темы поиска (по проектам) ─────────────────────────────────────
SEARCH_TOPICS = [
    # CDATA
    {"query": "centriole aging stem cell", "label": "CDATA", "max": 3},
    {"query": "centriolar damage accumulation aging", "label": "CDATA", "max": 2},
    # ZeAnastasis / EEG
    {"query": "EEG aging biomarker cognitive decline", "label": "Ze/EEG", "max": 3},
    {"query": "heart rate variability aging longevity", "label": "Ze/HRV", "max": 2},
    # Integrative Medicine
    {"query": "integrative medicine longevity clinical", "label": "Integrative", "max": 3},
    # Regenesis / phytomedicine
    {"query": "phytomedicine longevity protocol", "label": "Regenesis", "max": 2},
    # General aging/geroscience
    {"query": "hallmarks aging 2025 2026", "label": "Geroscience", "max": 3},
    {"query": "digital twin aging simulation", "label": "CDATA/DT", "max": 2},
    # Dietebi / clinical nutrition
    {"query": "clinical nutrition therapeutic diet aging", "label": "Dietebi", "max": 2},
]

OUTPUT_DIR = os.path.expanduser("~/Desktop/AIM/literature_digest")


# ── PubMed eutils ─────────────────────────────────────────────────
def search_pubmed(query: str, max_results: int = 3) -> list[dict]:
    """Returns list of {title, authors, journal, year, pmid, url}"""
    try:
        base = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/"
        q = urllib.parse.quote(query + " AND (\"2024\"[dp] OR \"2025\"[dp] OR \"2026\"[dp])")
        search_url = f"{base}esearch.fcgi?db=pubmed&term={q}&retmax={max_results}&retmode=json&sort=date"
        with urllib.request.urlopen(search_url, timeout=10) as r:
            data = json.loads(r.read())
        ids = data.get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []
        ids_str = ",".join(ids)
        summary_url = f"{base}esummary.fcgi?db=pubmed&id={ids_str}&retmode=json"
        with urllib.request.urlopen(summary_url, timeout=10) as r:
            sdata = json.loads(r.read())
        results = []
        for pmid in ids:
            art = sdata.get("result", {}).get(pmid, {})
            if not art or pmid == "uids":
                continue
            authors = ", ".join(a.get("name", "") for a in art.get("authors", [])[:3])
            if len(art.get("authors", [])) > 3:
                authors += " et al."
            results.append({
                "title": art.get("title", "").rstrip("."),
                "authors": authors,
                "journal": art.get("fulljournalname", art.get("source", "")),
                "year": art.get("pubdate", "")[:4],
                "pmid": pmid,
                "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
                "source": "PubMed",
            })
        return results
    except Exception as e:
        return []


# ── bioRxiv / medRxiv via CrossRef ───────────────────────────────
def search_biorxiv(query: str, max_results: int = 2) -> list[dict]:
    try:
        q = urllib.parse.quote(query)
        url = (f"https://api.crossref.org/works?query={q}"
               f"&filter=from-pub-date:2024-01-01,type:posted-content"
               f"&rows={max_results}&sort=published&order=desc"
               f"&select=title,author,published,URL,container-title")
        req = urllib.request.Request(url, headers={"User-Agent": "AIM-LiteratureMonitor/1.0 (mailto:drjaba@aim.ge)"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        items = data.get("message", {}).get("items", [])
        results = []
        for it in items:
            title = it.get("title", [""])[0]
            authors_raw = it.get("author", [])
            authors = ", ".join(f"{a.get('family', '')} {a.get('given', '')[:1]}" for a in authors_raw[:3])
            if len(authors_raw) > 3:
                authors += " et al."
            pub = it.get("published", {}).get("date-parts", [[""]])[0]
            year = str(pub[0]) if pub else ""
            server = it.get("container-title", ["preprint"])[0] if it.get("container-title") else "preprint"
            link = it.get("URL", "")
            if not title or not link:
                continue
            results.append({
                "title": title,
                "authors": authors,
                "journal": server,
                "year": year,
                "pmid": "",
                "url": link,
                "source": "bioRxiv/medRxiv",
            })
        return results
    except Exception:
        return []


# ── Semantic Scholar ──────────────────────────────────────────────
def search_semantic_scholar(query: str, max_results: int = 2) -> list[dict]:
    try:
        q = urllib.parse.quote(query)
        url = (f"https://api.semanticscholar.org/graph/v1/paper/search"
               f"?query={q}&limit={max_results}&fields=title,authors,year,venue,externalIds,openAccessPdf"
               f"&publicationDateOrYear=2024:")
        req = urllib.request.Request(url, headers={"User-Agent": "AIM-LiteratureMonitor/1.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        items = data.get("data", [])
        results = []
        for it in items:
            title = it.get("title", "")
            authors_raw = it.get("authors", [])
            authors = ", ".join(a.get("name", "") for a in authors_raw[:3])
            if len(authors_raw) > 3:
                authors += " et al."
            year = str(it.get("year", ""))
            venue = it.get("venue", "")
            ext = it.get("externalIds", {})
            pmid = ext.get("PubMed", "")
            pdf = it.get("openAccessPdf", {})
            link = pdf.get("url", "") if pdf else ""
            if pmid:
                link = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            elif not link:
                ss_id = it.get("paperId", "")
                link = f"https://www.semanticscholar.org/paper/{ss_id}" if ss_id else ""
            if not title:
                continue
            results.append({
                "title": title,
                "authors": authors,
                "journal": venue,
                "year": year,
                "pmid": pmid,
                "url": link,
                "source": "Semantic Scholar",
            })
        return results
    except Exception:
        return []


# ── Аннотация через DeepSeek ──────────────────────────────────────
def annotate_articles(articles: list[dict]) -> list[dict]:
    if not articles:
        return []
    items_text = "\n".join(
        f"{i+1}. [{a['source']}] {a['title']} / {a['authors']} / {a['journal']} {a['year']}"
        for i, a in enumerate(articles)
    )
    prompt = (
        "Ниже список научных статей. Для каждой напиши ОДНО предложение на русском языке: "
        "суть находки/метода и почему важно. Формат строго: '1. Текст.' '2. Текст.' и т.д. "
        "Не добавляй ничего лишнего.\n\n" + items_text
    )
    response = ask_llm(prompt, max_tokens=800, temperature=0.1, model=MODEL_FAST)
    lines = {int(l.split(".")[0]): ".".join(l.split(".")[1:]).strip()
             for l in response.strip().split("\n")
             if l.strip() and l[0].isdigit()}
    for i, a in enumerate(articles):
        a["annotation_ru"] = lines.get(i + 1, "")
    return articles


# ── Формирование дайджеста ────────────────────────────────────────
def build_digest(all_articles: list[tuple[str, list[dict]]]) -> str:
    now = datetime.datetime.now()
    lines = [
        f"# AIM Literature Digest — {now.strftime('%Y-%m-%d %H:%M')}",
        f"_Автоматический сбор статей по темам проектов Dr. Jaba Tkemaladze_",
        "",
    ]
    for label, articles in all_articles:
        if not articles:
            continue
        lines.append(f"## {label}")
        for a in articles:
            title = a.get("title", "").strip()
            authors = a.get("authors", "")
            journal = a.get("journal", "")
            year = a.get("year", "")
            url = a.get("url", "")
            ann = a.get("annotation_ru", "")
            lines.append(f"**{title}**  ")
            lines.append(f"{authors} / *{journal}* {year}  ")
            if url:
                lines.append(f"🔗 {url}  ")
            if ann:
                lines.append(f"📝 {ann}")
            lines.append("")
    if not any(arts for _, arts in all_articles):
        lines.append("_Новых статей не найдено._")
    return "\n".join(lines)


# ── Очистка старых дайджестов ─────────────────────────────────────
def cleanup_old_digests(digest_dir: str, days: int = 183):
    """Удалить .md файлы старше days дней."""
    if not os.path.isdir(digest_dir):
        return
    cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
    removed = 0
    for fname in os.listdir(digest_dir):
        if not fname.endswith(".md"):
            continue
        fpath = os.path.join(digest_dir, fname)
        try:
            mtime = datetime.datetime.fromtimestamp(os.path.getmtime(fpath))
            if mtime < cutoff:
                os.remove(fpath)
                removed += 1
        except Exception:
            pass
    if removed:
        print(f"  [cleanup] Удалено {removed} устаревших дайджестов (>{days} дней)")


# ── Основной поток ────────────────────────────────────────────────
def run():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    cleanup_old_digests(OUTPUT_DIR)
    now = datetime.datetime.now()
    fname = now.strftime("%Y-%m-%d_%H") + ".md"
    out_path = os.path.join(OUTPUT_DIR, fname)

    print(f"[{now.strftime('%H:%M')}] AIM Literature Monitor — старт")

    all_results: list[tuple[str, list[dict]]] = []
    seen_titles: set[str] = set()

    for topic in SEARCH_TOPICS:
        label = topic["label"]
        query = topic["query"]
        mx = topic["max"]
        arts: list[dict] = []

        # PubMed
        for a in search_pubmed(query, mx):
            key = a["title"].lower()[:60]
            if key not in seen_titles:
                seen_titles.add(key)
                arts.append(a)
        time.sleep(0.4)  # respect rate limits

        # bioRxiv — только для научных тем
        for a in search_biorxiv(query, 1):
            key = a["title"].lower()[:60]
            if key not in seen_titles:
                seen_titles.add(key)
                arts.append(a)
        time.sleep(0.3)

        # Semantic Scholar
        for a in search_semantic_scholar(query, 1):
            key = a["title"].lower()[:60]
            if key not in seen_titles:
                seen_titles.add(key)
                arts.append(a)
        time.sleep(0.3)

        # Аннотации через DeepSeek
        arts = annotate_articles(arts)
        all_results.append((label, arts))
        total = sum(len(a) for _, a in all_results)
        print(f"  [{label}] {len(arts)} статей (всего {total})")

    digest = build_digest(all_results)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(digest)

    total = sum(len(a) for _, a in all_results)
    print(f"[{now.strftime('%H:%M')}] Готово — {total} статей → {out_path}")
    return out_path


if __name__ == "__main__":
    run()
