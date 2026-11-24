import argparse
import json
import sys
from datetime import datetime

from app.core.config import BASE_DIR, get_settings
from app.evaluation.caching_llm import CachingLLMClient
from app.evaluation.generation_eval import CaseResult, evaluate_case, summarize
from app.evaluation.judges import AnswerJudge
from app.evaluation.poison import PoisonedRetrieval
from app.llm.groq_client import GroqLLMClient
from app.rag.embeddings import Embedder
from app.services.chat_service import ChatService
from app.services.retrieval_service import RetrievalService

CASES_PATH = BASE_DIR / "evaluations" / "generation_cases.json"
RESULTS_DIR = BASE_DIR / "evaluations" / "results"
CACHE_DIR = BASE_DIR / "evaluations" / "cache"


def fmt(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.2f}"


def print_case(item: CaseResult, show_answers: bool) -> None:
    status = "PASS" if item.passed else "FAIL"
    scores = ""

    if item.faithfulness is not None or item.relevancy is not None:
        scores = f" | fid={fmt(item.faithfulness)} rel={fmt(item.relevancy)}"

    print(f"[{status}] {item.id} {item.category} | {item.path}{scores} | {item.latency_ms}ms")

    if not item.passed:
        for failure in item.failures:
            print(f"       - {failure}")

    if item.path != "documentacao_resposta" and item.path.startswith("documentacao"):
        print(f"       - score={item.max_score:.3f} busca: {item.search_query}")

    for claim in item.unsupported_claims:
        print(f"       - sem suporte: {claim}")

    if item.relevancy is not None and item.relevancy < 0.75 and item.relevancy_note:
        print(f"       - relevância: {item.relevancy_note}")

    if show_answers or not item.passed:
        print(f"       resposta: {item.answer[:600]}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt-version", default=None)
    parser.add_argument("--no-judge", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--delay", type=float, default=None)
    parser.add_argument("--only", default=None)
    parser.add_argument("--show-answers", action="store_true")
    parser.add_argument("--repeat", type=int, default=1)
    parser.add_argument("--resample", action="store_true")
    args = parser.parse_args()

    settings = get_settings()
    updates = {}

    if args.prompt_version:
        updates["prompt_version"] = args.prompt_version

    if args.delay is not None:
        updates["llm_min_interval_seconds"] = args.delay

    settings = settings.model_copy(update=updates)

    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]

    if args.only:
        wanted = {item.strip() for item in args.only.split(",")}
        cases = [case for case in cases if case["id"] in wanted or case["category"] in wanted]

    retrieval = RetrievalService(settings, Embedder(settings.embedding_model_name))
    retrieval.load()
    retrieval.warm_up()

    llm = CachingLLMClient(
        GroqLLMClient(settings),
        CACHE_DIR,
        use_cache=not args.no_cache,
        resample=args.resample,
    )
    base_service = ChatService(settings, retrieval, llm)
    judge = None if args.no_judge else AnswerJudge(llm)

    print(
        f"prompt={settings.prompt_version} | modelo={settings.groq_model} | "
        f"casos={len(cases)} | avaliadores={'desligados' if judge is None else 'ligados'}"
    )
    print()

    results = []
    plan = [case for _ in range(args.repeat) for case in cases]

    for position, case in enumerate(plan, start=1):
        print(f"[{position}/{len(plan)}] {case['id']}", file=sys.stderr)

        service = base_service

        if case.get("inject_context"):
            service = ChatService(settings, PoisonedRetrieval(retrieval, case["inject_context"]), llm)

        item = evaluate_case(case, service, judge)
        results.append(item)
        print_case(item, args.show_answers)

    summary = summarize(results, {case["id"]: case for case in cases})

    if args.repeat > 1:
        print()
        print(f"Repetições por caso: {args.repeat}")

        for case in cases:
            runs = [item for item in results if item.id == case["id"]]
            paths = sorted({item.path for item in runs})
            print(f"  {case['id']}: {sum(1 for item in runs if item.passed)}/{len(runs)} passaram | rotas: {paths}")

    print()
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print()
    print(
        f"Chamadas ao Groq: novas={llm.misses} | do cache={llm.hits} | "
        f"tokens gastos: entrada={llm.prompt_tokens} saída={llm.completion_tokens}"
    )

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    prefix = "repeat" if args.repeat > 1 else "generation"
    output = RESULTS_DIR / f"{prefix}_{settings.prompt_version}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output.write_text(
        json.dumps(
            {
                "prompt_version": settings.prompt_version,
                "settings": {
                    "evidence_threshold": settings.evidence_threshold,
                    "top_k": settings.top_k,
                    "query_analysis_enabled": settings.query_analysis_enabled,
                    "model": settings.groq_model,
                    "judges": judge is not None,
                    "only": args.only,
                    "cases": len(cases),
                },
                "summary": summary,
                "cases": [item.__dict__ for item in results],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Resultado salvo em {output}")


if __name__ == "__main__":
    main()