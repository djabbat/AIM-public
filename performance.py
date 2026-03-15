#!/usr/bin/env python3
import os
import time
from concurrent.futures import ThreadPoolExecutor

class PerformanceOptimizer:
    def __init__(self):
        self.stats = {
            'total_scans': 0,
            'total_analyses': 0,
            'avg_scan_time': 0,
            'avg_analysis_time': 0,
            'cache_hits': 0,
            'cache_misses': 0
        }
        self.config = {
            'max_workers': 4,
            'scan_interval': 5,
            'cache_enabled': True,
            'cache_size': 100,
            'parallel_analysis': True,
            'batch_size': 10,
            'timeout': 30
        }
        self.cache = {}
        self.cache_timestamps = {}
    
    def scan_projects_optimized(self, desktop_path, existing_projects, security):
        start = time.time()
        try:
            current = set(os.listdir(desktop_path))
            existing = set(existing_projects.keys())
            new_projects = []
            for item in current:
                path = os.path.join(desktop_path, item)
                if os.path.isdir(path) and not item.startswith('.') and item not in existing:
                    if security:
                        files = security.filter_project_files(path)['valid']
                    else:
                        files = []
                    new_projects.append((item, path, files))
            
            self.stats['total_scans'] += 1
            elapsed = time.time() - start
            self.stats['avg_scan_time'] = (self.stats['avg_scan_time'] * (self.stats['total_scans'] - 1) + elapsed) / self.stats['total_scans']
            return new_projects
        except Exception as e:
            print(f"Ошибка сканирования: {e}")
            return []
    
    def optimize_config(self, projects_count):
        if projects_count < 10:
            self.config['max_workers'] = 2
            self.config['batch_size'] = 5
        elif projects_count < 50:
            self.config['max_workers'] = 4
            self.config['batch_size'] = 10
        else:
            self.config['max_workers'] = 8
            self.config['batch_size'] = 20
        return self.config
    
    def clear_cache(self):
        size = len(self.cache)
        self.cache.clear()
        self.cache_timestamps.clear()
        return size
    
    def get_performance_report(self):
        report = []
        report.append("\n📊 ОТЧЕТ О ПРОИЗВОДИТЕЛЬНОСТИ")
        report.append("="*50)
        report.append(f"Сканирований: {self.stats['total_scans']}")
        report.append(f"Среднее время: {self.stats['avg_scan_time']:.2f} сек")
        report.append(f"Кэш попаданий: {self.stats['cache_hits']}")
        report.append(f"Кэш промахов: {self.stats['cache_misses']}")
        report.append(f"\nКонфигурация:")
        report.append(f"  Workers: {self.config['max_workers']}")
        report.append(f"  Интервал: {self.config['scan_interval']} сек")
        return '\n'.join(report)
