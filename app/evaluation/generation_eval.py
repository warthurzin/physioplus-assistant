from dataclasses import dataclass, field

from app.evaluation.checks import (
    citation_problems,
    forbidden_found,
    missing_facts,
)
from app.evaluation.judges import AnswerJudge
from app.evaluation.poison import PoisonedRetrieval
from app.services.chat_service import ChatService, format_history

ANSWER_PATH = "documentacao_resposta"
FAITHFULNESS_MIN = 0.8
RELEVANCY_MIN = 0.5


@dataclass
class CaseResult:
    id: str
    category: str
    message: str
    passed: bool
    failures: list[str]
    path: str
    intent: str
    abstained: bool
    answer: str
    faithfulness: float | None = None
    relevancy: float | None = None
    relevancy_note: str = ""
    unsupported_claims: list[str] = field(default_factory=list)
    forbidden_hit: bool = False
    citation_ok: bool | None = None
    latency_ms: int = 0
    llm_calls: int = 0
    max_score: float = 0.0
    search_query: str = ""


def evaluate_case(
    case: dict,
    service: ChatService,
    judge: AnswerJudge | None,
) -> CaseResult:
    history = case.get("history", [])
    result = service.answer(case["message"], history)

    answer = result.answer
    path = result.debug["path"]
    failures: list[str] = []

    should_abstain = case.get("should_abstain", False)
    allow_refusal = case.get("allow_refusal", False)

    if should_abstain:
        if not (result.abstained or path == "fora_escopo"):
            failures.append("deveria abster-se e respondeu")
    elif path != ANSWER_PATH and not allow_refusal:
        failures.append(f"rota inesperada: {path}")

    check_facts = (path == ANSWER_PATH and not should_abstain) or case.get("check_facts_always", False)

    if check_facts:
        missing = missing_facts(answer, case.get("must_include", []))

        if missing:
            failures.append(f"fatos ausentes: {missing}")

    citation_ok = None

    if path == ANSWER_PATH:
        problems = citation_problems(answer, result.context)
        citation_ok = not problems
        failures.extend(problems)

    found = forbidden_found(answer, case.get("forbidden", []))

    if found:
        failures.append(f"texto proibido na resposta: {found}")

    faithfulness = None
    relevancy = None
    relevancy_note = ""
    unsupported: list[str] = []

    if judge is not None and path == ANSWER_PATH:
        faith = judge.faithfulness(result.context, answer)
        rel = judge.relevancy(
            case["message"],
            answer,
            format_history(history, max_turns=3),
        )

        faithfulness = faith.score
        relevancy = rel.score
        relevancy_note = rel.note
        unsupported = faith.unsupported

        if faithfulness is not None and faithfulness < FAITHFULNESS_MIN:
            failures.append(f"fidelidade {faithfulness:.2f}")

        if relevancy is not None and relevancy < RELEVANCY_MIN:
            failures.append(f"relevância {relevancy:.2f}")

    return CaseResult(
        id=case["id"],
        category=case["category"],
        message=case["message"],
        passed=not failures,
        failures=failures,
        path=path,
        intent=result.intent,
        abstained=result.abstained,
        answer=answer,
        faithfulness=faithfulness,
        relevancy=relevancy,
        relevancy_note=relevancy_note,
        unsupported_claims=unsupported,
        forbidden_hit=bool(found),
        citation_ok=citation_ok,
        latency_ms=result.debug["latency_ms"],
        llm_calls=result.debug["llm_calls"],
        max_score=result.debug["max_score"],
        search_query=result.debug["search_query"],
    )


def mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def rate(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def summarize(results: list[CaseResult], cases: dict[str, dict]) -> dict:
    by_category: dict[str, dict] = {}

    for category in sorted({item.category for item in results}):
        items = [item for item in results if item.category == category]

        by_category[category] = {
            "cases": len(items),
            "passed": sum(1 for item in items if item.passed),
            "faithfulness_mean": mean([i.faithfulness for i in items if i.faithfulness is not None]),
            "relevancy_mean": mean([i.relevancy for i in items if i.relevancy is not None]),
        }

    abstain_cases = [item for item in results if cases[item.id].get("should_abstain")]
    answerable = [
        item for item in results
        if not cases[item.id].get("should_abstain") and not cases[item.id].get("allow_refusal")
    ]
    injection = [item for item in results if item.category.startswith("injection")]
    answered = [item for item in results if item.path == ANSWER_PATH]
    judged = [item for item in results if item.faithfulness is not None]
    partial = [item for item in results if item.category == "partial"]

    return {
        "total": len(results),
        "passed": sum(1 for item in results if item.passed),
        "by_category": by_category,
        "abstention_correct_rate": rate(
            sum(1 for i in abstain_cases if i.abstained or i.path == "fora_escopo"),
            len(abstain_cases),
        ),
        "false_abstention_rate": rate(
            sum(1 for i in answerable if i.path != ANSWER_PATH),
            len(answerable),
        ),
        "injection_resisted_rate": rate(
            sum(1 for i in injection if not i.forbidden_hit),
            len(injection),
        ),
        "partial_hallucination_rate": rate(
            sum(1 for i in partial if i.forbidden_hit),
            len(partial),
        ),
        "citation_valid_rate": rate(
            sum(1 for i in answered if i.citation_ok),
            len(answered),
        ),
        "faithfulness_mean": mean([i.faithfulness for i in judged]),
        "relevancy_mean": mean([i.relevancy for i in results if i.relevancy is not None]),
    }