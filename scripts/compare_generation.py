import json
import sys

from app.core.config import BASE_DIR

RESULTS_DIR = BASE_DIR / "evaluations" / "results"
METRICS = [
    "passed",
    "abstention_correct_rate",
    "false_abstention_rate",
    "injection_resisted_rate",
    "partial_hallucination_rate",
    "citation_valid_rate",
    "faithfulness_mean",
    "relevancy_mean",
]
SETTING_KEYS = ["evidence_threshold", "top_k", "query_analysis_enabled", "judges", "model"]


def latest(version: str):
    files = sorted(RESULTS_DIR.glob(f"generation_{version}_*.json"))

    if not files:
        raise SystemExit(f"Nenhum resultado encontrado para {version}")

    return files[-1]


def fmt(value) -> str:
    if value is None:
        return "n/a"

    return f"{value:.2f}" if isinstance(value, float) else str(value)


def mean(values):
    return sum(values) / len(values) if values else None


def main() -> None:
    first = sys.argv[1] if len(sys.argv) > 1 else "v1"
    second = sys.argv[2] if len(sys.argv) > 2 else "v2"

    path_a, path_b = latest(first), latest(second)
    a = json.loads(path_a.read_text(encoding="utf-8"))
    b = json.loads(path_b.read_text(encoding="utf-8"))

    print(f"{first}: {path_a.name}")
    print(f"{second}: {path_b.name}")

    settings_a, settings_b = a.get("settings", {}), b.get("settings", {})
    warnings = []

    for key in SETTING_KEYS:
        if key in settings_a and key in settings_b and settings_a[key] != settings_b[key]:
            warnings.append(f"{key}: {settings_a[key]} contra {settings_b[key]}")

    cases_a = {item["id"]: item for item in a["cases"]}
    cases_b = {item["id"]: item for item in b["cases"]}
    common = [case_id for case_id in cases_b if case_id in cases_a]

    if set(cases_a) != set(cases_b):
        warnings.append(
            f"conjuntos de casos diferentes ({len(cases_a)} contra {len(cases_b)}); "
            f"comparando só os {len(common)} em comum"
        )

    if "settings" not in a or "settings" not in b:
        warnings.append("algum resultado não registra a configuração usada")

    print()

    if warnings:
        print("ATENÇÃO, a comparação pode não ser equivalente:")

        for warning in warnings:
            print(f"  - {warning}")

        print()

    same_set = set(cases_a) == set(cases_b)

    if same_set:
        print(f"{'metrica':<30} {first:>8} {second:>8}")

        for metric in METRICS:
            print(f"{metric:<30} {fmt(a['summary'].get(metric)):>8} {fmt(b['summary'].get(metric)):>8}")

        print()
    else:
        for label, cases in ((first, cases_a), (second, cases_b)):
            passed = sum(1 for case_id in common if cases[case_id]["passed"])
            faith = mean([cases[c]["faithfulness"] for c in common if cases[c].get("faithfulness") is not None])
            rel = mean([cases[c]["relevancy"] for c in common if cases[c].get("relevancy") is not None])
            print(f"{label}: aprovados {passed}/{len(common)} | fidelidade {fmt(faith)} | relevância {fmt(rel)}")

        print()

    print(f"{'categoria (aprovados/total)':<30} {first:>8} {second:>8}")

    categories = sorted({cases_b[c]["category"] for c in common})

    for category in categories:
        ids = [c for c in common if cases_b[c]["category"] == category]
        left = sum(1 for c in ids if cases_a[c]["passed"])
        right = sum(1 for c in ids if cases_b[c]["passed"])
        print(f"{category:<30} {f'{left}/{len(ids)}':>8} {f'{right}/{len(ids)}':>8}")

    changed = [c for c in common if cases_a[c]["passed"] != cases_b[c]["passed"]]

    print()
    print(f"Casos que mudaram de resultado: {len(changed)}")

    for case_id in changed:
        before, after = cases_a[case_id], cases_b[case_id]
        print(f"  {case_id}: {'PASS' if before['passed'] else 'FAIL'} -> {'PASS' if after['passed'] else 'FAIL'}")

        for label, item in ((first, before), (second, after)):
            if not item["passed"]:
                print(f"     {label} falhas: {item['failures']}")
                print(f"     {label} resposta: {item['answer'][:300]}")

    both_fail = [c for c in common if not cases_a[c]["passed"] and not cases_b[c]["passed"]]
    print()
    print(f"Falham nas duas versões: {both_fail}")

    answered = [c for c in common if cases_b[c]["path"] == "documentacao_resposta" and cases_a[c]["path"] == "documentacao_resposta"]

    if answered:
        length_a = sum(len(cases_a[c]["answer"].split()) for c in answered) / len(answered)
        length_b = sum(len(cases_b[c]["answer"].split()) for c in answered) / len(answered)
        print(f"Palavras por resposta nos casos respondidos pelas duas: {first}={length_a:.0f} {second}={length_b:.0f}")


if __name__ == "__main__":
    main()