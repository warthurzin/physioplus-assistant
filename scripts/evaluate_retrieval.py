import argparse
import json
import sys
from datetime import datetime

from app.core.config import BASE_DIR, get_settings
from app.prompts import get_prompts
from app.rag.embeddings import Embedder
from app.rag.metrics import context_precision, context_recall
from app.services.query_analyzer import QueryAnalyzer
from app.services.retrieval_service import RetrievalService

CASES_PATH = BASE_DIR / "evaluations" / "retrieval_cases.json"
RESULTS_DIR = BASE_DIR / "evaluations" / "results"
THRESHOLDS = [0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55]


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--rewrite", action="store_true")
    parser.add_argument("--delay", type=float, default=None)
    args = parser.parse_args()

    settings = get_settings()

    if args.delay is not None:
        settings = settings.model_copy(update={"llm_min_interval_seconds": args.delay})
    service = RetrievalService(settings, Embedder(settings.embedding_model_name))
    service.load()

    analyzer = None

    if args.rewrite:
        from app.llm.groq_client import GroqLLMClient

        analyzer = QueryAnalyzer(
            GroqLLMClient(settings),
            get_prompts(settings.prompt_version),
            enabled=True,
        )

    top_k = args.top_k or settings.top_k
    cases = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]

    rows = []

    for position, case in enumerate(cases, start=1):
        query = case["question"]
        intent = None
        fallback = False

        if analyzer is not None:
            print(f"[{position}/{len(cases)}] {case['id']}", file=sys.stderr)
            result = analyzer.analyze(case["question"])
            query = result.analysis.standalone_question
            intent = result.analysis.intent
            fallback = result.analysis.fallback

        hits = service.search(query, top_k)
        retrieved_documents = [hit.chunk.document_id for hit in hits]
        expected = case["expected_documents"]

        row = {
            "id": case["id"],
            "split": case.get("split", "dev"),
            "question": case["question"],
            "search_query": query,
            "intent": intent,
            "expected_intent": case.get("expected_intent"),
            "analysis_fallback": fallback,
            "in_domain": case["in_domain"],
            "expected_documents": expected,
            "retrieved_documents": retrieved_documents,
            "max_score": hits[0].score if hits else 0.0,
            "top_document": retrieved_documents[0] if retrieved_documents else None,
        }

        if case["in_domain"]:
            row["context_recall"] = context_recall(retrieved_documents, expected)
            row["context_precision"] = context_precision(retrieved_documents, expected)
            row["top1_correct"] = row["top_document"] in expected

        rows.append(row)

    in_domain = [row for row in rows if row["in_domain"]]
    out_domain = [
        row for row in rows
        if not row["in_domain"] and row["expected_intent"] != "DADOS_OU_ACAO"
    ]
    routing_only = [
        row for row in rows
        if not row["in_domain"] and row["expected_intent"] == "DADOS_OU_ACAO"
    ]

    mode = "com reescrita por LLM" if args.rewrite else "sem reescrita"
    print(
        f"top_k={top_k} | {mode} | no domínio={len(in_domain)} | "
        f"fora do domínio={len(out_domain)} | apenas roteamento={len(routing_only)}"
    )
    print()

    for row in rows:
        extra = ""

        if args.rewrite:
            extra = f" intent={row['intent']}"

            if row["search_query"] != row["question"]:
                extra += f" | busca: {row['search_query']}"

        if row["in_domain"]:
            print(
                f"{row['id']} recall={row['context_recall']:.2f} "
                f"precision={row['context_precision']:.2f} "
                f"top1={'ok' if row['top1_correct'] else 'ERRO'} "
                f"score={row['max_score']:.3f} top={row['top_document']}{extra}"
            )
        elif row["expected_intent"] == "DADOS_OU_ACAO":
            print(f"{row['id']} apenas roteamento{extra}")
        else:
            print(
                f"{row['id']} fora do domínio score={row['max_score']:.3f} "
                f"top={row['top_document']}{extra}"
            )

    summary = {}

    for split in sorted({row["split"] for row in rows}):
        split_rows = [row for row in in_domain if row["split"] == split]

        entry = {
            "retrieval_cases": len(split_rows),
            "context_recall_mean": mean([row["context_recall"] for row in split_rows]),
            "context_precision_mean": mean([row["context_precision"] for row in split_rows]),
            "top1_accuracy": mean([1.0 if row["top1_correct"] else 0.0 for row in split_rows]),
            "min_score": min((row["max_score"] for row in split_rows), default=0.0),
        }

        if args.rewrite:
            routed = [
                row for row in rows
                if row["split"] == split and row["expected_intent"] is not None
            ]
            entry["routing_cases"] = len(routed)
            entry["routing_accuracy"] = mean(
                [1.0 if row["intent"] == row["expected_intent"] else 0.0 for row in routed]
            )

        summary[split] = entry

    print()
    print(json.dumps({"top_k": top_k, "rewrite": args.rewrite, **summary}, indent=2))

    if args.rewrite:
        errors = [
            row for row in rows
            if row["expected_intent"] is not None and row["intent"] != row["expected_intent"]
        ]
        fallbacks = [row["id"] for row in rows if row["analysis_fallback"]]

        print()
        print(f"Erros de roteamento: {len(errors)}")

        for row in errors:
            print(f"  {row['id']} esperado={row['expected_intent']} obtido={row['intent']} | {row['question']}")

        print(f"Análises que caíram no fallback: {fallbacks}")

    print()
    print("Calibração do limiar de evidência")
    print("limiar | no domínio aceitas | fora do domínio rejeitadas")

    sweep = []

    for threshold in THRESHOLDS:
        accepted = sum(1 for row in in_domain if row["max_score"] >= threshold)
        rejected = sum(1 for row in out_domain if row["max_score"] < threshold)
        sweep.append(
            {"threshold": threshold, "in_domain_accepted": accepted, "out_domain_rejected": rejected}
        )
        print(f"{threshold:.2f}   | {accepted}/{len(in_domain)}              | {rejected}/{len(out_domain)}")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "rewrite" if args.rewrite else "baseline"
    output = RESULTS_DIR / f"retrieval_{suffix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output.write_text(
        json.dumps(
            {"summary": {"top_k": top_k, "rewrite": args.rewrite, **summary}, "sweep": sweep, "cases": rows},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print()
    print(f"Resultado salvo em {output}")


if __name__ == "__main__":
    main()