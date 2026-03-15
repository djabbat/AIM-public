#!/usr/bin/env python3
import json
import os
from datetime import datetime, timedelta

class ProjectMemory:
    def __init__(self, memory_file="~/AIM/projects_memory.json"):
        self.memory_file = os.path.expanduser(memory_file)
        self.memory = self.load()
    
    def load(self):
        if os.path.exists(self.memory_file):
            try:
                with open(self.memory_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except:
                return {"projects": {}, "last_scan": None, "statistics": {}}
        else:
            return {"projects": {}, "last_scan": None, "statistics": {}}
    
    def save(self):
        with open(self.memory_file, 'w', encoding='utf-8') as f:
            json.dump(self.memory, f, indent=2, ensure_ascii=False)
    
    def add_project(self, name, path, files):
        if name not in self.memory["projects"]:
            self.memory["projects"][name] = {
                "first_seen": datetime.now().isoformat(),
                "path": path,
                "analyses": [],
                "changes": []
            }
        self.memory["projects"][name]["last_seen"] = datetime.now().isoformat()
        self.memory["projects"][name]["file_count"] = len(files)
        self.memory["last_scan"] = datetime.now().isoformat()
        self.save()
    
    def add_analysis(self, name, analysis):
        if name in self.memory["projects"]:
            if "analyses" not in self.memory["projects"][name]:
                self.memory["projects"][name]["analyses"] = []
            self.memory["projects"][name]["analyses"].append({
                "date": datetime.now().isoformat(),
                "content": analysis[:200]
            })
            self.save()
    
    def get_statistics(self):
        stats = {
            "total_projects": len(self.memory["projects"]),
            "total_analyses": 0,
            "projects_by_type": {},
            "last_scan": self.memory["last_scan"]
        }
        for name, data in self.memory["projects"].items():
            stats["total_analyses"] += len(data.get("analyses", []))
        return stats
    
    def get_project_history(self, name):
        return self.memory["projects"].get(name)
    
    def get_changed_projects(self, hours=24):
        changed = []
        cutoff = datetime.now() - timedelta(hours=hours)
        for name, data in self.memory["projects"].items():
            if "last_seen" in data:
                last_seen = datetime.fromisoformat(data["last_seen"])
                if last_seen > cutoff:
                    changed.append(name)
        return changed
    
    def clear_old_memory(self, days=30):
        cutoff = datetime.now() - timedelta(days=days)
        to_delete = []
        for name, data in self.memory["projects"].items():
            if "last_seen" in data:
                last_seen = datetime.fromisoformat(data["last_seen"])
                if last_seen < cutoff:
                    to_delete.append(name)
        for name in to_delete:
            del self.memory["projects"][name]
        self.save()
        return len(to_delete)
