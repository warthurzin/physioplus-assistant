# Engenharia de prompt do Assistente Physio+

Registro das decisões e dos resultados da Etapa 3. Os números vêm das execuções reais com o modelo `qwen/qwen3.8-27b` no Groq.

## Pipeline

```
mensagem + histórico
   -> analyze (LLM, JSON): intenção + pergunta reescrita com os termos do aplicativo
        DOCUMENTACAO   -> retrieve (FAISS, top 5) -> pontuação >= limiar (0,35)?
                              sim -> generate (LLM, citações [Fonte N])
                                       -> verify (LLM, opcional) -> aprovada | rejeitada -> abstenção
                              não -> abstain (resposta fixa)
        SAUDACAO / DADOS_OU_ACAO / FORA_ESCOPO -> respostas fixas
```

Cada etapa tem prompt, responsabilidade e métrica próprios. O prompt de geração e o de verificação são separados.

## Prompts

| Prompt | Arquivo | Função |
|---|---|---|
| Análise (v1, compartilhado) | `app/prompts/v1.py` | Classifica a intenção e reescreve a pergunta. Zero-shot com exemplos de fronteira (few-shot) entre documentação e dados ou ação. |
| Geração v1 | `app/prompts/v1.py` | Linha de base. Usa só o contexto, abstém-se com frase fixa, cita fontes. |
| Geração v2 | `app/prompts/v2.py` | Experimento rejeitado. |
| Geração v3 | `app/prompts/v3.py` | Padrão. |
| Verificação | `app/prompts/verification.py` | Decide se a resposta é sustentada pelo contexto (JSON `suportada`). |

Técnicas aplicadas: separação entre instruções (system) e dados (contexto, histórico, pergunta) por delimitadores, tratamento do conteúdo recuperado e do histórico como dado não confiável, contrato de saída em JSON validado no código, few-shot, decomposição em etapas encadeadas (LangGraph) e roteamento condicional.

## Versões da geração

| Versão | O que muda | Resultado |
|---|---|---|
| v1 | Regras básicas | 54 de 55 casos. Falha: q02 (não menciona o captcha). Responde "o contexto não informa". |
| v2 | Proíbe deduzir e obriga o prefixo de abstenção quando falta informação | Rejeitada. Em 37 casos (limiar 0,35), regrediu p04 e p06 e manteve p03: respondia "Não encontrei" mesmo tendo a informação. Abstenção indevida de 12,5%. A fidelidade 1,00 era efeito de abster-se mais. |
| v3 | v1 mais: responder à pergunta original (a reformulada só apoia a busca), tratar "não é possível" como resposta, permitir combinar trechos citados, usar o prefixo de abstenção só quando nada é dito sobre o assunto, dizer "documentação" | Padrão. 55 de 55 casos. |

Amostragem repetida (5 execuções por caso, temperatura 0,1):

| Caso | v1 | v3 |
|---|---|---|
| j03 (injeção no contexto) | 5/5 | 5/5 |
| p04 (e-mail no perfil) | 5/5 | 5/5 |
| q02 (conta bloqueada e captcha) | 1/5 | 3/5 |

A falha isolada do j03 na primeira rodada do v3 era ruído. A vantagem do v3 no q02 é consistente com o desenho, mas a amostra é pequena e ele ainda omite o captcha em 2 de 5 vezes.

## Método de avaliação

- **Recuperação** (`scripts/evaluate_retrieval.py`): Context Recall, Context Precision, acerto do primeiro resultado, acurácia de roteamento e calibração do limiar de evidência. Conjuntos `dev`, `holdout`, `holdout2` e `holdout3`, cada um escrito antes de ver os resultados do anterior.
- **Geração** (`scripts/evaluate_generation.py`, 55 casos): documentação, coloquial, follow-up, casos difíceis, informação parcial, abstenção e injeção (direta, no contexto e no histórico).
  - Checagens por código: rota, fatos obrigatórios, citações válidas, texto proibido, abstenção correta.
  - Avaliadores por LLM: fidelidade (afirmações suportadas pelo contexto) e relevância.
  - Cache em disco de todas as chamadas e amostragem repetida sem sobrescrever o cache.
- **Controles dos avaliadores** (`scripts/check_judges.py`): pares conhecidos (resposta fiel, meio inventada, totalmente inventada, dependente do histórico, relevante, de outro assunto, recusa indevida, resposta parcial). Fidelidade 4/4 e relevância 4/4. A rubrica de relevância foi corrigida depois de o primeiro controle falhar: ela penalizava a ausência de passo a passo que a base não contém.
- **Comparação** (`scripts/compare_generation.py`): avisa quando limiar, `top_k` ou conjunto de casos diferem.

## Resultados

Recuperação, acerto do primeiro resultado (sem e com reescrita da pergunta):

| Conjunto | Sem reescrita | Com reescrita |
|---|---|---|
| dev (20) | 0,95 | 1,00 |
| holdout (8) | 0,75 | 1,00 |
| holdout2 (9) | 0,78 | 0,89 |
| holdout3 (7) | 0,86 | 0,86 |

Acurácia de roteamento da análise: 25 de 26 em `dev` e 100% nos três conjuntos de validação. Os conjuntos `holdout` e `holdout2` já tinham sido vistos quando o prompt de análise foi ajustado, e o `holdout3` é o teste limpo (sem ganho da reescrita nele). Estes números foram medidos antes das últimas correções da base e não foram repetidos.

Geração (55 casos, limiar 0,35): abstenção correta 10 de 10, abstenção indevida 0, citações válidas em 100%, fidelidade média 1,00, relevância média 0,99, alucinação nos casos de informação parcial 0 de 3.

Injeção de prompt (12 casos, resistidos em 12, nas duas versões):
- 6 diretas (em português, em inglês, em base64, tentativa de vazar o prompt, mudança de papel), 5 no contexto (instrução, link malicioso, desconto falso, tag falsa, pedido de vazamento) e 1 no histórico forjado.
- Nas diretas e no histórico, o analisador desviou o pedido para fora de escopo antes da geração. A geração foi exercitada de fato nas 5 injeções no contexto e em `i03`.

Verificação: implementada atrás de `VERIFY_ANSWERS` (padrão desligado) e coberta por controles sintéticos em `scripts/check_verifier.py`. No conjunto de 55 casos a geração não produziu respostas sem suporte (fidelidade 1,00), então o verificador não tem o que capturar ali: o custo (uma chamada a mais, cerca de 1,5 mil tokens) é certo e o benefício não foi medido. Em caso de falha do verificador, a resposta é mantida e o fato aparece no `debug` como `indisponivel`.

## Limites conhecidos

- Conjuntos pequenos, escritos pelo mesmo autor da base. Diferenças de um caso não são significativas.
- O avaliador é o mesmo modelo que gera, o que pode favorecer as próprias respostas. Os controles mitigam, mas não eliminam isso.
- Os ataques são simples. Não cobrem envenenamento por fato falso nem ataques adaptativos.
- A base foi escrita a partir da API e da especificação. As correções de conteúdo (pagamento, financeiro, captcha, exclusão de conta) vieram do responsável pelo produto. A linguagem ainda é a da API em alguns pontos.
- Recuperação: os casos k05 e m01 continuam com o documento certo fora da primeira posição.
- Cerca de 8% das chamadas ao Groq excedem o timeout de 8 s e dependem do rodízio de chaves.
- A geração usa temperatura 0,1, então respostas variam entre execuções.

## Como reproduzir

```
python -m scripts.build_index
python -m scripts.evaluate_retrieval --top-k 5 --rewrite --delay 20
python -m scripts.check_judges
python -m scripts.evaluate_generation --delay 20 --prompt-version v3
python -m scripts.compare_generation v1 v3
python -m scripts.evaluate_generation --delay 20 --prompt-version v3 --only j03,q02,p04 --repeat 5 --resample --no-judge
python -m scripts.check_verifier
```