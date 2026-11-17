# Integração das ações com o coordenador Node

O chat e o histórico permanecem stateless. `ActionService.propose()` conserva a preparação/resolução de pacientes existente e obtém um snapshot autenticado em `GET assistant/context/:patientId`. Nome, dados, agendamentos, sessões e revisões vêm desse snapshot; revisões são strings BIGINT e não entram no histórico ou na interface.

O `AssistantCommandSigner` cria UUID v4 e bytes Ed25519 uma vez. O envelope inteiro é guardado em proposta Fernet v2. A confirmação reutiliza esse envelope sem assinar novamente ou reconstruir JSON. As propostas Fernet v1 anteriores não são mais executáveis e retornam `invalid`, sem fallback para as rotas de escrita antigas.

`POST /chat/confirm` mantém entrada `{proposal}` e saída `{status,message,action}`. Seu limite de token sobe de 4.000 para 40.000 caracteres para acomodar o envelope criptografado. A validade de novos comandos é `min(PROPOSAL_TTL_SECONDS, 300)`. Expiração final é responsabilidade do Node/relógio PostgreSQL: um envelope expirado pode somente recuperar um resultado terminal anterior ou ser recusado, sem nova escrita.

`POST /chat/result`, com o mesmo payload e autenticação, consulta um resultado sem executar operação. Usar POST evita colocar o token opaco em URL/logs de acesso; internamente chama exclusivamente GET `assistant/executions/:executionId`. Fechamento de widget ainda descarta a proposta, conforme frontend existente; o widget atual oferece consulta do resultado incerto enquanto a conversa permanece aberta.

Não há retry de escrita. Timeout/falha HTTP na confirmação pode ser seguido por uma consulta GET de reconciliação. 401/422 não provocam renovação ou reenvio automático. Falha também na leitura permanece `unavailable`; não é evidência de que a operação deixou de ocorrer. O Node devolve `unknown` se não consegue determinar o resultado; esse estado é traduzido para `unavailable`, compatível com o frontend atual. Mensagens terminais do Node são genéricas e não expõem nomes/CPF/identificadores internos.

## Configuração

As ações permanecem desabilitadas por padrão. Em um ambiente validado, São exigidos DATA_TOOLS_ENABLED, ACTIONS_ENABLED e o novo ASSISTANT_EXECUTIONS_ENABLED; PATIENT_ACTIONS_ENABLED bloqueia adicionalmente as ações de pacientes na preparação e confirmação.

- ASSISTANT_SIGNING_SECRET: segredo Fernet persistente e igual entre instâncias, requisito anterior preservado.
- ASSISTANT_COMMAND_KEY_ID: ID da chave pública previamente confiada pelo Node.
- ASSISTANT_COMMAND_PRIVATE_KEY: PEM PKCS8 Ed25519 privado, representado por SecretStr. Nunca reutilizar segredo Fernet ou JWT profissional. Não há geração automática de chave em produção.
- PHYSIO_API_BASE_URL: base existente do Node, preservada.

Configuração inválida de assinatura desabilita ações sem impedir o chat de leitura. Flags não representam desligamento simultâneo entre instâncias. Não foram criadas chaves de produção nem alterados arquivos .env. A autenticação continua validada por `/auth/me` antes de propostas, confirmações e recuperação.

As oito ações estão conectadas ao coordenador. No Neon exclusivo de testes autorizado, as migrations 001–017 foram aplicadas e verificadas (`revisions_ready`), com 95 verificações reais de estrutura/constraints e 13 cenários integrados de concorrência, rollback, expiração, autorização, recuperação e das oito ações. Os 43 testes Python isolados passaram. O piloto HTTP local gerou propostas, descartou uma sem escrita, confirmou outra com exatamente um agendamento e recuperou o resultado sem duplicação; o usuário validou a confirmação visual no navegador. Esses resultados não aplicam migrations nem habilitam ações em produção.

## Operação e limitações

- Node recebe o Bearer profissional e valida `/auth/me`; Python não recebe o segredo JWT. O Node verifica o comando Ed25519 e associa o comprovante ao profissional autenticado.
- `ASSISTANT_SIGNING_SECRET` deve ser persistente e consistente entre instâncias Python; `ASSISTANT_COMMAND_PRIVATE_KEY` e o `ASSISTANT_COMMAND_KEY_ID` devem corresponder a uma chave pública confiável configurada no Node. Chaves temporárias de teste não são configuração de produção.
- `PHYSIO_API_BASE_URL` aponta ao prefixo `/api/v1` do Node. `CORS_ORIGINS` inclui somente as origens profissionais autorizadas. No frontend, as URLs Node e Python são distintas.
- O Node deve ter migrations 016/017 aplicadas no ambiente específico antes de ativar `ASSISTANT_EXECUTIONS_ENABLED`. Ações de pacientes exigem também as flags próprias em Python e Node. Flags são carregadas por processo; não há desligamento instantâneo global.
- Em timeout ou rede incerta, consultar `/chat/result`; não repetir automaticamente `/chat/confirm`. Ao fechar o widget, o token local é descartado, portanto uma recuperação posterior à conversa aberta não é oferecida pela interface. Comprovantes compactos exigem política operacional de retenção antes de expurgo.

## Verificação isolada

```powershell
.venv/Scripts/python.exe -m scripts.check_action_safety
.venv/Scripts/python.exe -m scripts.check_idempotent_actions
.venv/Scripts/python.exe -m scripts.check_command_signer --node-backend '<caminho do physioPlus-backend>'
```

Os scripts usam configuração construída em memória, transportes simulados e chaves temporárias. Não carregam .env, não executam pytest e não acessam banco/API real. Interoperabilidade executa efetivamente o verificador Node informado.
