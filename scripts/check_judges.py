from app.core.config import BASE_DIR, get_settings
from app.evaluation.caching_llm import CachingLLMClient
from app.evaluation.judge_controls import HIGH_MIN, LOW_MAX, MID_MAX, MID_MIN, run_controls
from app.evaluation.judges import AnswerJudge
from app.llm.groq_client import GroqLLMClient

CACHE_DIR = BASE_DIR / "evaluations" / "cache"


def main() -> None:
    settings = get_settings()
    llm = CachingLLMClient(GroqLLMClient(settings), CACHE_DIR)
    results = run_controls(AnswerJudge(llm))

    print(
        f"Controles dos avaliadores | alto >= {HIGH_MIN} | medio {MID_MIN} a {MID_MAX} | baixo <= {LOW_MAX}"
    )
    print()

    for item in results:
        score = "n/a" if item.score is None else f"{item.score:.2f}"
        status = "OK  " if item.ok else "ERRO"
        print(f"[{status}] {item.kind:<11} {item.name:<22} esperado={item.expected:<6} nota={score}")

        if item.detail:
            print(f"       {item.detail}")

    failures = [item for item in results if not item.ok]

    print()
    print(f"Controles corretos: {len(results) - len(failures)}/{len(results)}")
    print(f"Chamadas novas: {llm.misses} | do cache: {llm.hits}")


if __name__ == "__main__":
    main()