from dataclasses import dataclass

from app.evaluation.judges import AnswerJudge

CONTEXT = (
    "[Fonte 1 - Pagamento de sessões > Como o pagamento é registrado]\n"
    "O pagamento é registrado em cada sessão. A operação de pagamento funciona como alternância: "
    "ao ser executada, marca a sessão como paga, e ao ser executada de novo, desfaz o pagamento."
)

QUESTION = "Como registro o pagamento de uma sessão?"

FAITHFULNESS_CONTROLS = [
    (
        "fiel",
        "O pagamento é registrado em cada sessão. Executar a operação de novo desfaz o pagamento. [Fonte 1]",
        "alto",
    ),
    (
        "meio inventada",
        "O pagamento é registrado em cada sessão. Executar a operação de novo desfaz o pagamento. "
        "O sistema envia um recibo por e-mail ao paciente a cada pagamento e permite parcelar em até 3 vezes. [Fonte 1]",
        "medio",
    ),
    (
        "totalmente inventada",
        "O pagamento é feito por cartão de crédito com taxa de 2%, e o valor cai na conta em até 30 dias. [Fonte 1]",
        "baixo",
    ),
    (
        "depende do histórico",
        "Como mencionado antes na conversa, o pagamento fica pendente até o paciente quitar o boleto enviado por e-mail.",
        "baixo",
    ),
]

RELEVANCY_CONTROLS = [
    (
        "relevante",
        QUESTION,
        "O pagamento é registrado em cada sessão. A operação marca a sessão como paga, e executá-la de novo desfaz o pagamento.",
        "alto",
    ),
    (
        "de outro assunto",
        QUESTION,
        "A Agenda pode ser consultada por dia ou por semana, informando uma data no formato AAAA-MM-DD.",
        "baixo",
    ),
    (
        "recusa indevida",
        QUESTION,
        "Posso ajudar apenas com dúvidas sobre o uso do PhysioPlus. Não consigo responder a esse assunto.",
        "baixo",
    ),
    (
        "responde so metade",
        "Como cadastro um paciente e o que acontece se eu repetir o CPF de outro paciente?",
        "Para cadastrar um paciente é preciso informar nome completo, CPF, telefone e valor da sessão.",
        "medio",
    ),
]

HIGH_MIN = 0.75
LOW_MAX = 0.25
MID_MIN = 0.25
MID_MAX = 0.75


@dataclass(frozen=True)
class ControlResult:
    kind: str
    name: str
    expected: str
    score: float | None
    ok: bool
    detail: str


def is_ok(expected: str, score: float | None) -> bool:
    if score is None:
        return False

    if expected == "alto":
        return score >= HIGH_MIN

    if expected == "medio":
        return MID_MIN <= score <= MID_MAX

    return score <= LOW_MAX


def run_controls(judge: AnswerJudge) -> list[ControlResult]:
    results = []

    for name, answer, expected in FAITHFULNESS_CONTROLS:
        outcome = judge.faithfulness(CONTEXT, answer)
        results.append(
            ControlResult(
                kind="fidelidade",
                name=name,
                expected=expected,
                score=outcome.score,
                ok=is_ok(expected, outcome.score),
                detail="; ".join(outcome.unsupported) or outcome.note,
            )
        )

    for name, question, answer, expected in RELEVANCY_CONTROLS:
        outcome = judge.relevancy(question, answer)
        results.append(
            ControlResult(
                kind="relevância",
                name=name,
                expected=expected,
                score=outcome.score,
                ok=is_ok(expected, outcome.score),
                detail=outcome.note,
            )
        )

    return results