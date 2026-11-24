from app.core.config import BASE_DIR, get_settings
from app.evaluation.caching_llm import CachingLLMClient
from app.evaluation.judge_controls import CONTEXT, FAITHFULNESS_CONTROLS
from app.llm.groq_client import GroqLLMClient
from app.services.answer_verifier import APPROVED, REJECTED, AnswerVerifier

CACHE_DIR = BASE_DIR / "evaluations" / "cache"


def main() -> None:
    settings = get_settings()
    llm = CachingLLMClient(GroqLLMClient(settings), CACHE_DIR)
    verifier = AnswerVerifier(llm)

    print("Controles do verificador")
    print()

    correct = 0

    for name, answer, expected_level in FAITHFULNESS_CONTROLS:
        expected = APPROVED if expected_level == "alto" else REJECTED
        result = verifier.verify(CONTEXT, answer)
        ok = result.verdict == expected
        correct += int(ok)

        print(f"[{'OK  ' if ok else 'ERRO'}] {name:<22} esperado={expected:<9} obtido={result.verdict}")
        print(f"       {result.note}")

    print()
    print(f"Controles corretos: {correct}/{len(FAITHFULNESS_CONTROLS)}")
    print(f"Chamadas novas: {llm.misses} | do cache: {llm.hits}")


if __name__ == "__main__":
    main()