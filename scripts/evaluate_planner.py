import argparse
import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.config import BASE_DIR, get_settings
from app.evaluation.caching_llm import CachingLLMClient
from app.evaluation.planner_eval import evaluate_planner_case
from app.llm.groq_client import GroqLLMClient
from app.services.data_planner import DataPlanner

CASES_PATH = BASE_DIR / "evaluations" / "planner_cases.json"
CACHE_DIR = BASE_DIR / "evaluations" / "cache"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delay", type=float, default=None)
    args = parser.parse_args()

    settings = get_settings()

    if args.delay is not None:
        settings = settings.model_copy(update={"llm_min_interval_seconds": args.delay})

    llm = CachingLLMClient(GroqLLMClient(settings), CACHE_DIR)
    planner = DataPlanner(llm, settings.timezone)
    now = datetime.now(ZoneInfo(settings.timezone))
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]

    print(f"Hoje: {planner.today_text()} | casos={len(cases)}")
    print()

    results = []

    for position, case in enumerate(cases, start=1):
        print(f"[{position}/{len(cases)}] {case['id']}", file=sys.stderr)
        item = evaluate_planner_case(case, planner, now)
        results.append(item)
        print(f"[{'PASS' if item.passed else 'FAIL'}] {item.id} | {item.got_tool} {item.got_args if item.got_args else ''}")

        for problem in item.problems:
            print(f"       - {problem}")

    print()
    prefixes = {"f": "financeiro", "s": "busca de pacientes", "p": "perfil de paciente", "u": "não suportado", "h": "follow-up", "x": "injeção", "n": "pagamento pendente", "c": "mensagem vaga", "a": "agenda", "w": "ações com confirmação", "q": "ações de paciente"}

    for prefix, label in prefixes.items():
        group = [item for item in results if item.id.startswith(prefix)]
        print(f"{label:<22} {sum(1 for i in group if i.passed)}/{len(group)}")

    print()
    print(f"Total: {sum(1 for i in results if i.passed)}/{len(results)}")
    print(f"Chamadas novas: {llm.misses} | do cache: {llm.hits} | tokens: entrada={llm.prompt_tokens} saída={llm.completion_tokens}")


if __name__ == "__main__":
    main()