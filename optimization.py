#!/usr/bin/env python3
import os
import time
import psutil
import threading
from datetime import datetime
import gc

class MemoryOptimizer:
    """Оптимизация использования памяти"""
    
    def __init__(self):
        self.memory_threshold = 80  # процент использования памяти
        self.cache_cleanup_interval = 3600  # 1 час
        self.last_cleanup = time.time()
        self.memory_stats = []
    
    def get_memory_usage(self):
        """Получает текущее использование памяти"""
        process = psutil.Process(os.getpid())
        memory_info = process.memory_info()
        return {
            'rss': memory_info.rss / 1024 / 1024,  # MB
            'vms': memory_info.vms / 1024 / 1024,  # MB
            'percent': process.memory_percent()
        }
    
    def check_memory(self):
        """Проверяет использование памяти"""
        usage = self.get_memory_usage()
        self.memory_stats.append({
            'time': datetime.now(),
            'usage': usage
        })
        
        # Оставляем только последние 100 записей
        if len(self.memory_stats) > 100:
            self.memory_stats = self.memory_stats[-100:]
        
        return usage
    
    def auto_cleanup(self, force=False):
        """Автоматическая очистка памяти"""
        current_time = time.time()
        usage = self.get_memory_usage()
        
        if force or usage['percent'] > self.memory_threshold or current_time - self.last_cleanup > self.cache_cleanup_interval:
            print(f"🧹 Очистка памяти (использовано: {usage['percent']:.1f}%)")
            
            # Принудительная сборка мусора
            collected = gc.collect()
            
            # Очистка кэшей
            self.last_cleanup = current_time
            
            return {
                'cleaned': collected,
                'before': usage,
                'after': self.get_memory_usage()
            }
        return None

class CacheOptimizer:
    """Оптимизация кэширования"""
    
    def __init__(self, max_size=100):
        self.cache = {}
        self.max_size = max_size
        self.hits = 0
        self.misses = 0
        self.access_count = {}
    
    def get(self, key):
        """Получает значение из кэша"""
        if key in self.cache:
            self.hits += 1
            self.access_count[key] = self.access_count.get(key, 0) + 1
            return self.cache[key]
        self.misses += 1
        return None
    
    def set(self, key, value):
        """Сохраняет значение в кэш"""
        if len(self.cache) >= self.max_size:
            # Удаляем наименее используемые
            least_used = sorted(self.access_count.items(), key=lambda x: x[1])[:10]
            for k, _ in least_used:
                if k in self.cache:
                    del self.cache[k]
                if k in self.access_count:
                    del self.access_count[k]
        
        self.cache[key] = value
        self.access_count[key] = self.access_count.get(key, 0) + 1
    
    def clear(self):
        """Очищает кэш"""
        size = len(self.cache)
        self.cache.clear()
        self.access_count.clear()
        return size
    
    def get_stats(self):
        """Статистика кэша"""
        total = self.hits + self.misses
        hit_rate = (self.hits / total * 100) if total > 0 else 0
        return {
            'size': len(self.cache),
            'max_size': self.max_size,
            'hits': self.hits,
            'misses': self.misses,
            'hit_rate': hit_rate,
            'usage': len(self.cache) / self.max_size * 100
        }

class QueryOptimizer:
    """Оптимизация запросов к Ollama"""
    
    def __init__(self):
        self.query_stats = []
        self.cache = CacheOptimizer(max_size=50)
    
    def optimize_prompt(self, prompt, max_length=2000):
        """Оптимизирует промпт для отправки"""
        if len(prompt) <= max_length:
            return prompt
        
        # Сокращаем промпт, сохраняя ключевую информацию
        lines = prompt.split('\n')
        if len(lines) > 50:
            # Оставляем начало и конец
            start = lines[:25]
            end = lines[-25:]
            optimized = '\n'.join(start) + '\n...\n' + '\n'.join(end)
        else:
            optimized = prompt[:max_length] + '...'
        
        return optimized
    
    def log_query(self, query, response_time, tokens):
        """Логирует запрос для статистики"""
        self.query_stats.append({
            'time': datetime.now(),
            'length': len(query),
            'response_time': response_time,
            'tokens': tokens
        })
        
        if len(self.query_stats) > 100:
            self.query_stats = self.query_stats[-100:]
    
    def get_avg_response_time(self):
        """Среднее время ответа"""
        if not self.query_stats:
            return 0
        return sum(q['response_time'] for q in self.query_stats) / len(self.query_stats)
    
    def get_stats(self):
        """Статистика запросов"""
        if not self.query_stats:
            return {}
        
        total_time = sum(q['response_time'] for q in self.query_stats)
        avg_time = total_time / len(self.query_stats)
        total_tokens = sum(q.get('tokens', 0) for q in self.query_stats)
        
        return {
            'total_queries': len(self.query_stats),
            'avg_response_time': avg_time,
            'total_time': total_time,
            'total_tokens': total_tokens,
            'avg_tokens': total_tokens / len(self.query_stats) if total_tokens else 0
        }

class PerformanceMonitor:
    """Мониторинг производительности"""
    
    def __init__(self):
        self.operations = {}
        self.running = False
        self.thread = None
    
    def start_monitoring(self):
        """Запускает мониторинг"""
        self.running = True
        self.thread = threading.Thread(target=self._monitor, daemon=True)
        self.thread.start()
    
    def stop_monitoring(self):
        """Останавливает мониторинг"""
        self.running = False
    
    def _monitor(self):
        """Фоновый мониторинг"""
        while self.running:
            self.check_performance()
            time.sleep(60)  # Проверка каждую минуту
    
    def log_operation(self, name, duration):
        """Логирует время выполнения операции"""
        if name not in self.operations:
            self.operations[name] = []
        
        self.operations[name].append({
            'time': datetime.now(),
            'duration': duration
        })
        
        # Оставляем только последние 100
        if len(self.operations[name]) > 100:
            self.operations[name] = self.operations[name][-100:]
    
    def get_slow_operations(self, threshold=1.0):
        """Возвращает медленные операции (> threshold секунд)"""
        slow = []
        for op_name, ops in self.operations.items():
            for op in ops:
                if op['duration'] > threshold:
                    slow.append({
                        'operation': op_name,
                        'duration': op['duration'],
                        'time': op['time']
                    })
        return sorted(slow, key=lambda x: x['duration'], reverse=True)
    
    def check_performance(self):
        """Проверяет производительность и выдает рекомендации"""
        issues = []
        
        # Проверяем медленные операции
        slow_ops = self.get_slow_operations(2.0)
        if slow_ops:
            issues.append(f"Найдено {len(slow_ops)} медленных операций")
        
        # Проверяем использование памяти
        try:
            import psutil
            memory = psutil.virtual_memory()
            if memory.percent > 80:
                issues.append(f"Высокое использование памяти: {memory.percent}%")
        except:
            pass
        
        return issues
    
    def get_stats(self):
        """Статистика производительности"""
        stats = {}
        for op_name, ops in self.operations.items():
            durations = [o['duration'] for o in ops]
            if durations:
                stats[op_name] = {
                    'avg': sum(durations) / len(durations),
                    'min': min(durations),
                    'max': max(durations),
                    'count': len(durations)
                }
        return stats

class Optimizer:
    """Главный класс оптимизации"""
    
    def __init__(self):
        self.memory = MemoryOptimizer()
        self.query = QueryOptimizer()
        self.monitor = PerformanceMonitor()
        self.cache = CacheOptimizer()
        self.stats = {
            'memory_saved': 0,
            'time_saved': 0,
            'optimizations': 0
        }
    
    def optimize_project_scan(self, projects):
        """Оптимизирует сканирование проектов"""
        # Кэшируем результаты сканирования
        cache_key = f"scan_{len(projects)}"
        cached = self.cache.get(cache_key)
        if cached:
            self.stats['time_saved'] += 1
            return cached
        
        # Оптимизируем сканирование
        result = {
            'total': len(projects),
            'scanned': []
        }
        
        self.cache.set(cache_key, result)
        return result
    
    def optimize_analysis(self, project_data):
        """Оптимизирует анализ проекта"""
        # Оптимизируем промпт
        if 'files' in project_data:
            project_data['files'] = project_data['files'][:50]  # Ограничиваем количество
        
        return project_data
    
    def get_optimization_report(self):
        """Отчет об оптимизации"""
        report = []
        report.append("\n🚀 ОТЧЕТ ОБ ОПТИМИЗАЦИИ")
        report.append("="*50)
        
        # Память
        mem_usage = self.memory.check_memory()
        report.append(f"\n📊 ПАМЯТЬ:")
        report.append(f"  Использовано: {mem_usage['rss']:.1f} MB")
        report.append(f"  Процент: {mem_usage['percent']:.1f}%")
        
        # Кэш
        cache_stats = self.cache.get_stats()
        report.append(f"\n💾 КЭШ:")
        report.append(f"  Размер: {cache_stats['size']}/{cache_stats['max_size']}")
        report.append(f"  Попаданий: {cache_stats['hit_rate']:.1f}%")
        
        # Запросы
        query_stats = self.query.get_stats()
        if query_stats:
            report.append(f"\n📝 ЗАПРОСЫ:")
            report.append(f"  Всего: {query_stats['total_queries']}")
            report.append(f"  Среднее время: {query_stats['avg_response_time']:.2f} сек")
        
        # Производительность
        perf_stats = self.monitor.get_stats()
        if perf_stats:
            report.append(f"\n⚡ ПРОИЗВОДИТЕЛЬНОСТЬ:")
            for op, stat in perf_stats.items():
                report.append(f"  {op}: ср.{stat['avg']:.2f}с макс.{stat['max']:.2f}с")
        
        # Проблемы
        issues = self.monitor.check_performance()
        if issues:
            report.append(f"\n⚠️ ПРОБЛЕМЫ:")
            for issue in issues:
                report.append(f"  • {issue}")
        
        report.append("\n" + "="*50)
        return '\n'.join(report)
    
    def apply_optimizations(self):
        """Применяет все оптимизации"""
        print("\n🚀 Применение оптимизаций...")
        
        # Очистка памяти
        mem_result = self.memory.auto_cleanup(force=True)
        if mem_result:
            print(f"  ✅ Очищено объектов: {mem_result['cleaned']}")
            print(f"  📉 Память: {mem_result['before']['rss']:.1f}MB → {mem_result['after']['rss']:.1f}MB")
            self.stats['memory_saved'] += mem_result['before']['rss'] - mem_result['after']['rss']
        
        # Очистка кэша
        cache_size = self.cache.clear()
        print(f"  ✅ Очищен кэш: {cache_size} элементов")
        
        self.stats['optimizations'] += 1
        
        print(f"  📊 Статистика: {self.stats}")

# Тестирование
if __name__ == "__main__":
    opt = Optimizer()
    print(opt.get_optimization_report())
    opt.apply_optimizations()
