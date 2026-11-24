# Publicação da API Python

## Escolha de hospedagem

A primeira tentativa de homologação é na Vercel, sem habilitar escritas. `app/main.py` já exporta `app: FastAPI`; a plataforma reconhece esse caminho e usa o `lifespan` existente. A distribuição ainda precisa ser medida no build Linux e a memória e o tempo de inicialização precisam ser observados no preview. O limite padrão do bundle Python é 500 MB. O limite de 5 GB das Large Functions é beta, exige Fluid Compute e não elimina o limite de memória ou os cold starts. Projetos novos entram automaticamente no beta; para um projeto antigo elegível, a Vercel documenta `VERCEL_SUPPORT_LARGE_FUNCTIONS=1` e um novo deploy. Large Functions não oferecem Secure Compute nem Static IPs. Não considerar a API pronta para produção antes dessa medição.

O pacote local Windows usa Python 3.12, com `torch` CPU, Sentence Transformers, FAISS e LangGraph. Apenas a pasta `torch` ocupa cerca de 514 MB no ambiente local; esse número não estima o bundle Linux. `requirements.txt` fixa a variante CPU já usada nos testes, obtida da listagem oficial de wheels do PyTorch. O índice atual tem aproximadamente 144 KB, mas `index/` é ignorado pelo Git. O build configurado em `vercel.json` executa `python -m scripts.build_index` no Linux, a partir de `knowledge/`, e falha se os três arquivos do índice ou `model-cache/` não forem gerados. `includeFiles` acrescenta esses artefatos à função. Não enviar o índice ou o cache produzidos no Windows.

`SENTENCE_TRANSFORMERS_HOME=model-cache` deve estar disponível **no build e na execução**. O modelo público é baixado no build para essa pasta, que também é usada pelas instâncias da API. O filesystem da função é temporário: índice e modelo devem vir do bundle de cada deploy; não depender de downloads ou arquivos escritos em uma instância anterior. Em cada cold start, `lifespan` carrega o FAISS e aquece o modelo. Conferir no preview se o bundle realmente inclui o cache e se `/health` retorna `index_loaded=true`, `index_stale=false` e `llm_configured=true` sem demora incompatível com o frontend.

Se o build exceder o tamanho aceito, se a função exceder 2 GB no Hobby (ou 4 GB no Pro), ou se o cold start for incompatível com o widget, usar como alternativa um Web Service Python persistente no Render. A configuração equivalente é: Python 3.12, build `pip install -r requirements.txt && python -m scripts.build_index`, start `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, com `SENTENCE_TRANSFORMERS_HOME=model-cache`. Gerar o índice no **build**, não no pre-deploy nem no startup. Medir a memória antes de escolher o plano: o plano de 512 MB provavelmente é insuficiente para PyTorch; as opções publicadas de 2 GB e 4 GB custam, respectivamente, US$ 25/mês e US$ 85/mês por instância, sem extras. O plano gratuito adormece após 15 minutos sem tráfego.

Na Vercel, o Hobby é US$ 0/mês com cotas de uso, 2 GB de memória máxima e até 300 segundos por invocação com Fluid Compute. O Pro começa em US$ 20/mês, inclui crédito de uso e permite até 4 GB e 800 segundos; CPU ativa, memória provisionada e invocações são medidas. O custo real depende da região, tráfego e duração dos cold starts. Groq é cobrado separadamente conforme a conta usada.

## Configuração de homologação

1. Versionar e enviar estes arquivos à branch `feat/etapa6-integracao`; esta preparação não publica nem altera ambientes por si só.
2. No painel Vercel, criar um projeto a partir de `warthurzin/physioplus-assistant`, com diretório raiz do repositório e preset FastAPI. Manter a branch principal como produção e usar `feat/etapa6-integracao` para um **Preview**. `vercel.json` define o build e os arquivos incluídos. `.python-version` fixa a família Python 3.12. Confirmar Fluid Compute e a elegibilidade de Large Functions no painel antes de contar com mais de 500 MB.
3. Em **Project → Settings → Environment Variables**, cadastrar os nomes abaixo para Preview. Configurar as variáveis antes do primeiro deploy da branch; mudanças posteriores só valem depois de redeploy. Não carregar `.env` local nem o banco Neon de testes.
4. No checkout dessa branch, com a Vercel CLI instalada, executar `vercel link` e `vercel deploy` **sem** `--prod`, ou usar o botão de deploy de Preview da branch no painel. Não usar `vercel --prod` nesta homologação.
5. No URL do Preview, consultar `GET /health`. Exigir `status=ok`, índice carregado e não desatualizado, e Groq configurado. Testar `POST /chat` com Bearer de um profissional válido em homologação. Sem Bearer, `/chat`, `/chat/confirm` e `/chat/result` devem rejeitar a requisição. Com ações desabilitadas, não testar escrita real. Registrar no painel o tamanho do bundle, duração e memória do primeiro cold start e latência do chat.
6. Configurar `VITE_ASSISTANT_API_URL` do frontend de homologação com a origem HTTPS do Preview e incluir somente a origem HTTPS desse frontend em `CORS_ORIGINS`. O frontend chama Python diretamente; Python encaminha o Bearer para o Node.

Variáveis de homologação, sem valores secretos neste documento:

| Nome | Uso |
| --- | --- |
| `ENVIRONMENT` | Identificação do ambiente, por exemplo `staging`. |
| `CORS_ORIGINS` | Origens exatas, separadas por vírgula, dos frontends profissionais autorizados; sem caminho. |
| `ENABLE_DEBUG_ENDPOINTS` | `false`; não publicar `/debug/retrieval/search` nem o campo de debug do chat. |
| `PHYSIO_API_BASE_URL` | URL HTTPS da API Node do **mesmo ambiente**, terminando em `/api/v1`; nunca o Node local ou o banco Neon de testes em produção. |
| `PHYSIO_API_TIMEOUT_SECONDS` | Timeout para a API Node; padrão 8 segundos. |
| `GROQ_API_KEYS` ou `GROQ_API_KEY` | Credencial de Groq configurada no painel, nunca no Git. |
| `GROQ_MODEL`, `GROQ_REASONING_EFFORT` | Modelo e modo de raciocínio; conferir disponibilidade na conta Groq. |
| `LLM_TIMEOUT_SECONDS`, `LLM_CONNECT_TIMEOUT_SECONDS`, `FORCE_IPV4` | Timeouts e rede da integração Groq; usar os padrões salvo necessidade medida. |
| `EMBEDDING_MODEL_NAME` | Mesmo identificador do modelo no build e no runtime; padrão `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. |
| `SENTENCE_TRANSFORMERS_HOME` | `model-cache` no build e runtime para incluir o modelo no bundle. |
| `DATA_TOOLS_ENABLED` | Leitura de dados via Node; habilitar somente quando a API Node de homologação estiver acessível. |
| `ACTIONS_ENABLED`, `PATIENT_ACTIONS_ENABLED`, `ASSISTANT_EXECUTIONS_ENABLED` | **`false` em homologação inicial**; manter `false` em produção até autorização e validação específicas desse ambiente. |
| `ASSISTANT_SIGNING_SECRET` | Fernet persistente e igual entre instâncias apenas quando escritas forem habilitadas. |
| `ASSISTANT_COMMAND_KEY_ID`, `ASSISTANT_COMMAND_PRIVATE_KEY` | ID e PEM PKCS8 Ed25519 privados apenas quando escritas forem habilitadas; o PEM requer quebras de linha reais. A chave pública correspondente deve estar confiada pelo Node do mesmo ambiente. |

`KNOWLEDGE_DIR` e `INDEX_DIR` não precisam ser definidos: os padrões apontam para `knowledge/` e `index/` relativos ao código. `CHUNK_MAX_WORDS`, `CHUNK_OVERLAP_SENTENCES` e `PROMPT_VERSION` podem usar os padrões; se os parâmetros de chunk mudarem, reconstruir o índice no deploy. Demais ajustes opcionais estão em `app/core/config.py` e `.env.example`. O Python não acessa PostgreSQL diretamente e não precisa de `DATABASE_URL`.

Os contratos de `GET /health`, `POST /chat`, `POST /chat/confirm` e `POST /chat/result` não são alterados por esta preparação. Confirmações continuam desabilitadas enquanto as flags estiverem desligadas. Antes de ativá-las em qualquer ambiente real, confirmar a aplicação das migrations 016 e 017 **no banco correspondente do Node**, as chaves Ed25519 confiáveis, o segredo Fernet consistente e a cobertura operacional descrita em `docs/EXECUCAO_IDEMPOTENTE.md`. Não utilizar a configuração do piloto de testes como produção.

## Fontes da plataforma

- [Vercel: FastAPI, build após dependências, `app/main.py` e lifespan](https://vercel.com/docs/frameworks/backend/fastapi)
- [Vercel: Python, versões e controle do bundle](https://vercel.com/docs/functions/runtimes/python)
- [Vercel: Large Functions de até 5 GB em beta](https://vercel.com/changelog/vercel-functions-can-now-be-up-to-5-gb-in-package-size)
- [Vercel: limites de memória e duração](https://vercel.com/docs/functions/limitations) e [preços](https://vercel.com/pricing)
- [Sentence Transformers: `SENTENCE_TRANSFORMERS_HOME`](https://www.sbert.net/docs/package_reference/sentence_transformer/model.html)
- [PyTorch: wheels CPU](https://download.pytorch.org/whl/cpu/torch/)
- [Render: FastAPI](https://render.com/docs/deploy-fastapi), [filesystem efêmero](https://render.com/docs/deploys) e [preços](https://render.com/pricing)
