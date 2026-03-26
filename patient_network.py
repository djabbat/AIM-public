#!/usr/bin/env python3
"""
patient_network.py — Patient Cluster & Relationship Network for AIM.

Concepts:
  Cluster  — named group of patients (family, shared chat, friends, etc.)
  Relation — typed edge between two patients

One WhatsApp chat / one folder can contain data for multiple people.
The doctor specifies which entries belong to which person and links them.
"""

from __future__ import annotations
import sqlite3
from typing import Optional
import db as _db
from config import get_logger

log = get_logger("patient_network")

# ─────────────────────────────────────────────────────────────────────────────
# Relationship types
# ─────────────────────────────────────────────────────────────────────────────

RELATION_TYPES = {
    "spouse":       ("супруг/супруга",    "spouse"),
    "parent":       ("родитель",          "parent"),
    "child":        ("ребёнок",           "child"),
    "sibling":      ("брат/сестра",       "sibling"),
    "grandparent":  ("дедушка/бабушка",   "grandparent"),
    "grandchild":   ("внук/внучка",       "grandchild"),
    "friend":       ("друг/подруга",      "friend"),
    "colleague":    ("коллега",           "colleague"),
    "other":        ("другое",            "other"),
}

RELATION_ICONS = {
    "spouse":      "💑",
    "parent":      "👨‍👧",
    "child":       "👶",
    "sibling":     "👫",
    "grandparent": "👴",
    "grandchild":  "👶",
    "friend":      "🤝",
    "colleague":   "🏥",
    "other":       "🔗",
}

# ─────────────────────────────────────────────────────────────────────────────
# DB helpers (thin wrappers over db._connect / db._tx)
# ─────────────────────────────────────────────────────────────────────────────

def _conn():
    return _db._connect()

def _tx():
    return _db._tx()

# ─────────────────────────────────────────────────────────────────────────────
# Clusters — CRUD
# ─────────────────────────────────────────────────────────────────────────────

def create_cluster(name: str, description: str = "") -> int:
    """Create a new cluster, return its id."""
    with _tx() as conn:
        cur = conn.execute(
            "INSERT INTO clusters (name, description) VALUES (?,?)",
            (name.strip(), description.strip())
        )
    return cur.lastrowid


def list_clusters() -> list[sqlite3.Row]:
    """Return all clusters ordered by name."""
    return _conn().execute(
        "SELECT c.*, COUNT(cm.patient_id) AS member_count "
        "FROM clusters c LEFT JOIN cluster_members cm ON cm.cluster_id=c.id "
        "GROUP BY c.id ORDER BY c.name"
    ).fetchall()


def get_cluster(cluster_id: int) -> Optional[sqlite3.Row]:
    return _conn().execute(
        "SELECT * FROM clusters WHERE id=?", (cluster_id,)
    ).fetchone()


def delete_cluster(cluster_id: int) -> None:
    """Delete cluster and all its memberships (not the patients themselves)."""
    with _tx() as conn:
        conn.execute("DELETE FROM cluster_members WHERE cluster_id=?", (cluster_id,))
        conn.execute("DELETE FROM clusters WHERE id=?", (cluster_id,))


def rename_cluster(cluster_id: int, new_name: str) -> None:
    with _tx() as conn:
        conn.execute("UPDATE clusters SET name=? WHERE id=?", (new_name.strip(), cluster_id))


# ─────────────────────────────────────────────────────────────────────────────
# Cluster Members — CRUD
# ─────────────────────────────────────────────────────────────────────────────

def add_to_cluster(cluster_id: int, patient_id: int, role: str = "member") -> None:
    """Add patient to cluster. role: 'primary'|'member'."""
    with _tx() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO cluster_members (cluster_id, patient_id, role) VALUES (?,?,?)",
            (cluster_id, patient_id, role)
        )


def remove_from_cluster(cluster_id: int, patient_id: int) -> None:
    with _tx() as conn:
        conn.execute(
            "DELETE FROM cluster_members WHERE cluster_id=? AND patient_id=?",
            (cluster_id, patient_id)
        )


def get_cluster_members(cluster_id: int) -> list[sqlite3.Row]:
    """Return all patients in a cluster with their basic info."""
    return _conn().execute(
        """SELECT p.id, p.surname, p.name, p.dob, p.sex, cm.role,
                  p.folder_path
           FROM cluster_members cm
           JOIN patients p ON p.id = cm.patient_id
           WHERE cm.cluster_id = ?
           ORDER BY cm.role DESC, p.surname, p.name""",
        (cluster_id,)
    ).fetchall()


def get_patient_clusters(patient_id: int) -> list[sqlite3.Row]:
    """Return all clusters a patient belongs to."""
    return _conn().execute(
        """SELECT c.id, c.name, cm.role
           FROM cluster_members cm
           JOIN clusters c ON c.id = cm.cluster_id
           WHERE cm.patient_id = ?
           ORDER BY c.name""",
        (patient_id,)
    ).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Relationships — CRUD
# ─────────────────────────────────────────────────────────────────────────────

def link_patients(patient_id_1: int, patient_id_2: int,
                  relation_type: str, notes: str = "") -> int:
    """
    Define a relationship from patient_1 → patient_2.
    E.g. link_patients(mom_id, daughter_id, "parent")
    Returns relationship id.
    """
    if relation_type not in RELATION_TYPES:
        raise ValueError(f"Unknown relation type: {relation_type}. "
                         f"Valid: {list(RELATION_TYPES.keys())}")
    with _tx() as conn:
        cur = conn.execute(
            """INSERT INTO patient_relationships
               (patient_id_1, patient_id_2, relation_type, notes)
               VALUES (?,?,?,?)""",
            (patient_id_1, patient_id_2, relation_type, notes)
        )
    return cur.lastrowid


def unlink_patients(rel_id: int) -> None:
    with _tx() as conn:
        conn.execute("DELETE FROM patient_relationships WHERE id=?", (rel_id,))


def get_patient_relations(patient_id: int) -> list[sqlite3.Row]:
    """Return all relationships involving this patient (both directions)."""
    return _conn().execute(
        """SELECT pr.id, pr.relation_type, pr.notes,
                  p1.id AS p1_id, p1.surname AS p1_surname, p1.name AS p1_name,
                  p2.id AS p2_id, p2.surname AS p2_surname, p2.name AS p2_name
           FROM patient_relationships pr
           JOIN patients p1 ON p1.id = pr.patient_id_1
           JOIN patients p2 ON p2.id = pr.patient_id_2
           WHERE pr.patient_id_1 = ? OR pr.patient_id_2 = ?
           ORDER BY pr.relation_type""",
        (patient_id, patient_id)
    ).fetchall()


def get_all_relations() -> list[sqlite3.Row]:
    return _conn().execute(
        """SELECT pr.id, pr.relation_type, pr.notes,
                  p1.surname || ' ' || p1.name AS name1,
                  p2.surname || ' ' || p2.name AS name2
           FROM patient_relationships pr
           JOIN patients p1 ON p1.id = pr.patient_id_1
           JOIN patients p2 ON p2.id = pr.patient_id_2
           ORDER BY p1.surname"""
    ).fetchall()


# ─────────────────────────────────────────────────────────────────────────────
# Patient Map — Text Visualization
# ─────────────────────────────────────────────────────────────────────────────

def _sex_icon(sex: str) -> str:
    return {"M": "♂", "F": "♀"}.get(sex, "·")


def _patient_line(p: sqlite3.Row, role: str = "") -> str:
    sex = _sex_icon(p["sex"]) if "sex" in p.keys() else "·"
    dob = p["dob"] or "?"
    role_label = f"  [{role}]" if role and role != "member" else ""
    return f"  👤 {p['surname']} {p['name']}  {sex}  р.{dob}{role_label}"


def show_patient_map() -> str:
    """
    Build a full text patient network map.
    Returns a formatted string ready to print.
    """
    lines = []
    W = 58
    lines.append("═" * W)
    lines.append("  🗺  КАРТА ПАЦИЕНТОВ И СВЯЗЕЙ".center(W))
    lines.append("═" * W)

    # ── Clusters ──────────────────────────────────────────────
    clusters = list_clusters()
    patients_in_clusters: set[int] = set()

    if clusters:
        lines.append("")
        lines.append("  КЛАСТЕРЫ / ГРУППЫ:")
        for cl in clusters:
            lines.append(f"  ┌─ {cl['name']} {'─'*(W-6-len(cl['name']))}")
            if cl["description"]:
                lines.append(f"  │  📝 {cl['description']}")
            members = get_cluster_members(cl["id"])
            if members:
                for m in members:
                    lines.append(f"  │ {_patient_line(m, m['role'])}")
                    patients_in_clusters.add(m["id"])
            else:
                lines.append("  │  (пусто)")
            lines.append("  └" + "─" * (W - 3))
    else:
        lines.append("")
        lines.append("  (кластеров пока нет — создайте через меню G)")

    # ── Relationships ─────────────────────────────────────────
    all_rels = get_all_relations()
    if all_rels:
        lines.append("")
        lines.append("  СВЯЗИ МЕЖДУ ПАЦИЕНТАМИ:")
        for r in all_rels:
            icon = RELATION_ICONS.get(r["relation_type"], "🔗")
            rel_ru = RELATION_TYPES.get(r["relation_type"], ("?",))[0]
            note = f"  [{r['notes']}]" if r["notes"] else ""
            lines.append(f"  {icon} {r['name1']}  →  {r['name2']}  [{rel_ru}]{note}")

    # ── Solo patients (no cluster) ────────────────────────────
    all_pts = _conn().execute(
        "SELECT id, surname, name, dob, sex FROM patients ORDER BY surname, name"
    ).fetchall()
    solo = [p for p in all_pts if p["id"] not in patients_in_clusters]
    if solo:
        lines.append("")
        lines.append(f"  ПАЦИЕНТЫ БЕЗ ГРУППЫ ({len(solo)}):")
        for p in solo:
            lines.append(f"  · {p['surname']} {p['name']}  {_sex_icon(p['sex'])}  р.{p['dob'] or '?'}")

    lines.append("")
    lines.append(f"  Всего пациентов: {len(all_pts)}  |  "
                 f"Кластеров: {len(clusters)}  |  Связей: {len(all_rels)}")
    lines.append("═" * W)
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Interactive Cluster Manager (called from medical_system.py)
# ─────────────────────────────────────────────────────────────────────────────

def manage_clusters_interactive(patients: list[dict]) -> None:
    """Full interactive TUI for managing clusters and relationships."""

    def pick_patient(prompt: str) -> Optional[int]:
        print(f"\n{prompt}")
        for i, p in enumerate(patients, 1):
            print(f"  {i:2}. {p['name']}  (р. {p.get('dob','?')})")
        raw = input("Номер пациента (Enter = отмена): ").strip()
        if not raw:
            return None
        try:
            return patients[int(raw) - 1]["id"]
        except (ValueError, IndexError):
            print("  ✗ Неверный номер")
            return None

    def pick_cluster(prompt: str) -> Optional[int]:
        clusters = list_clusters()
        if not clusters:
            print("  Нет кластеров. Создайте сначала.")
            return None
        print(f"\n{prompt}")
        for i, c in enumerate(clusters, 1):
            print(f"  {i:2}. {c['name']}  ({c['member_count']} уч.)")
        raw = input("Номер кластера (Enter = отмена): ").strip()
        if not raw:
            return None
        try:
            return clusters[int(raw) - 1]["id"]
        except (ValueError, IndexError):
            print("  ✗ Неверный номер")
            return None

    SUB = {
        "1": "Создать кластер",
        "2": "Добавить пациента в кластер",
        "3": "Убрать пациента из кластера",
        "4": "Удалить кластер",
        "5": "Связать двух пациентов",
        "6": "Показать связи пациента",
        "7": "Удалить связь",
        "0": "Назад",
    }

    while True:
        print("\n  ─── Управление группами и связями ───")
        for k, v in SUB.items():
            print(f"  {k}. {v}")
        ch = input("  Выбор: ").strip()

        if ch == "0":
            break

        elif ch == "1":
            name = input("  Название кластера: ").strip()
            if not name:
                continue
            desc = input("  Описание (Enter = пропустить): ").strip()
            cid = create_cluster(name, desc)
            print(f"  ✅ Кластер создан (id={cid}): {name}")

        elif ch == "2":
            cid = pick_cluster("Выберите кластер:")
            if cid is None:
                continue
            pid = pick_patient("Выберите пациента:")
            if pid is None:
                continue
            role = input("  Роль (primary/member, Enter=member): ").strip() or "member"
            add_to_cluster(cid, pid, role)
            print("  ✅ Пациент добавлен в кластер")

        elif ch == "3":
            cid = pick_cluster("Выберите кластер:")
            if cid is None:
                continue
            members = get_cluster_members(cid)
            if not members:
                print("  Кластер пуст")
                continue
            print("  Участники:")
            for i, m in enumerate(members, 1):
                print(f"  {i}. {m['surname']} {m['name']}")
            raw = input("  Номер для удаления: ").strip()
            try:
                pid = members[int(raw) - 1]["id"]
                remove_from_cluster(cid, pid)
                print("  ✅ Удалён из кластера")
            except (ValueError, IndexError):
                print("  ✗ Неверный номер")

        elif ch == "4":
            cid = pick_cluster("Выберите кластер для удаления:")
            if cid is None:
                continue
            cl = get_cluster(cid)
            confirm = input(f"  Удалить кластер «{cl['name']}»? (y/N): ").strip().lower()
            if confirm == "y":
                delete_cluster(cid)
                print("  ✅ Кластер удалён")

        elif ch == "5":
            print("\n  Типы связей:")
            rtypes = list(RELATION_TYPES.keys())
            for i, k in enumerate(rtypes, 1):
                print(f"  {i}. {k}  ({RELATION_TYPES[k][0]})")
            try:
                rtype = rtypes[int(input("  Тип связи (номер): ")) - 1]
            except (ValueError, IndexError):
                print("  ✗ Неверный тип")
                continue
            pid1 = pick_patient("ПЕРВЫЙ пациент (источник связи):")
            if pid1 is None:
                continue
            pid2 = pick_patient("ВТОРОЙ пациент (цель связи):")
            if pid2 is None or pid2 == pid1:
                print("  ✗ Нельзя связать пациента с самим собой")
                continue
            notes = input("  Примечание (Enter = пусто): ").strip()
            rel_id = link_patients(pid1, pid2, rtype, notes)
            print(f"  ✅ Связь создана (id={rel_id}): "
                  f"{RELATION_TYPES[rtype][0]}")

        elif ch == "6":
            pid = pick_patient("Выберите пациента:")
            if pid is None:
                continue
            rels = get_patient_relations(pid)
            if not rels:
                print("  Нет связей")
                continue
            print("  Связи пациента:")
            for r in rels:
                icon = RELATION_ICONS.get(r["relation_type"], "🔗")
                rel_ru = RELATION_TYPES.get(r["relation_type"], ("?",))[0]
                if r["p1_id"] == pid:
                    other = f"{r['p2_surname']} {r['p2_name']}"
                    direction = "→"
                else:
                    other = f"{r['p1_surname']} {r['p1_name']}"
                    direction = "←"
                note = f" [{r['notes']}]" if r["notes"] else ""
                print(f"  {icon} {direction} {other}  [{rel_ru}]{note}  (id={r['id']})")

        elif ch == "7":
            all_rels = get_all_relations()
            if not all_rels:
                print("  Нет связей")
                continue
            print("  Все связи:")
            for r in all_rels:
                rel_ru = RELATION_TYPES.get(r["relation_type"], ("?",))[0]
                print(f"  id={r['id']}  {r['name1']} → {r['name2']}  [{rel_ru}]")
            try:
                rid = int(input("  id связи для удаления: "))
                unlink_patients(rid)
                print("  ✅ Связь удалена")
            except ValueError:
                print("  ✗ Неверный id")

        else:
            print("  ✗ Неверный выбор")
