```rust
// src/engine.rs
use crate::types::*;
use serde_json;
use std::collections::HashMap;
use std::path::Path;

/// Загружает алгоритмы из JSON-файла.
pub fn load_algorithms(path: &Path) -> Vec<Algorithm> {
    let file = std::fs::File::open(path).expect("Cannot open algorithms file");
    let reader = std::io::BufReader::new(file);
    serde_json::from_reader(reader).expect("Invalid JSON format for algorithms")
}

/// Детерминированный обход одного алгоритма.
/// Начиная с корневого узла, проходит по веткам, для которых условие истинно в `case.structured`.
/// Если узел содержит дифференциал, добавляет его в результат.
pub fn walk(case: &Case, algo: &Algorithm) -> Vec<Differential> {
    let node_map: HashMap<&str, &Node> = algo
        .nodes
        .iter()
        .map(|n| (n.id.as_str(), n))
        .collect();

    let mut result = Vec::new();
    let mut current_id = algo.root_node_id.as_str();

    loop {
        let node = match node_map.get(current_id) {
            Some(n) => n,
            None => break,
        };

        // Добавляем дифференциал текущего узла, если есть
        if let Some(ref diff) = node.differential {
            result.push(diff.clone());
        }

        // Ищем следующую ветку, для которой выполняется условие
        let mut next_id = None;
        for branch in &node.branches {
            if evaluate_condition(&branch.condition, &case.structured) {
                next_id = Some(branch.target_node_id.as_str());
                break;
            }
        }

        match next_id {
            Some(id) => current_id = id,
            None => break, // Нет подходящей ветки — завершаем
        }
    }

    result
}

/// Проверяет условие ветки на основе structured-полей кейса.
/// Ожидаемый формат условия: "symptom:value" или "symptom=value".
/// Если условие равно "default", всегда истинно.
fn evaluate_condition(condition: &str, structured: &HashMap<String, String>) -> bool {
    if condition == "default" {
        return true;
    }

    let parts: Vec<&str> = condition.split(&[':', '='][..]).collect();
    if parts.len() != 2 {
        return false;
    }
    let key = parts[0].trim();
    let value = parts[1].trim();
    structured.get(key).map(|v| v == value).unwrap_or(false)
}

/// Прогоняет walk по всем алгоритмам, вычисляет вероятности, сортирует по классу
/// (red_flag > common > rare) и нормализует сумму вероятностей к 1.0.
pub fn rank(case: &Case, algos: &[Algorithm]) -> Vec<Differential> {
    let mut diffs = Vec::new();

    for algo in algos {
        diffs.extend(walk(case, algo));
    }

    // Вычисление "сырой" вероятности для каждого дифференциала
    for diff in &mut diffs {
        let base = match diff.probability_class.as_str() {
            "red_flag" => 0.30,
            "common" => 0.50,
            "rare" => 0.10,
            _ => 0.0,
        };
        let penalty = if diff.probability_class == "common" {
            0.05 * diff.evidence_against.len() as f64
        } else {
            0.0
        };
        diff.probability = (base - penalty).max(0.0);
    }

    // Сортировка: red_flag первыми, затем common, затем rare
    diffs.sort_by(|a, b| {
        let order_a = match a.probability_class.as_str() {
            "red_flag" => 0,
            "common" => 1,
            _ => 2,
        };
        let order_b = match b.probability_class.as_str() {
            "red_flag" => 0,
            "common" => 1,
            _ => 2,
        };
        order_a.cmp(&order_b)
    });

    // Нормализация вероятностей к 1.0
    let total: f64 = diffs.iter().map(|d| d.probability).sum();
    if total > 0.0 {
        for diff in &mut diffs {
            diff.probability /= total;
        }
    }

    diffs
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::collections::HashMap;

    fn make_case(structured: HashMap<String, String>) -> Case {
        Case { structured }
    }

    fn make_algo(json: &str) -> Algorithm {
        serde_json::from_str(json).unwrap()
    }

    #[test]
    fn test_single_path_common() {
        let algo_json = r#"
        {
            "id": "a1",
            "name": "Flu test",
            "root_node_id": "n1",
            "nodes": [
                {
                    "id": "n1",
                    "branches": [
                        {"condition": "fever:yes", "target_node_id": "n2"}
                    ],
                    "differential": null
                },
                {
                    "id": "n2",
                    "branches": [],
                    "differential": {
                        "