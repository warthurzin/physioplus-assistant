# Ações com confirmação

> O fluxo de execução abaixo registra o desenho inicial. O contrato integrado e as garantias atuais estão em [EXECUCAO_IDEMPOTENTE.md](EXECUCAO_IDEMPOTENTE.md): comando Ed25519, comprovante idempotente no Node e recuperação por `/chat/result`.

O assistente consegue alterar dados do profissional em oito operações: criar agendamento, cancelar agendamento, confirmar atendimento, marcar o pagamento de uma sessão, cadastrar paciente, editar dados de paciente, desativar paciente e reativar paciente. Nenhuma alteração é feita sem confirmação explícita do usuário.

## Fluxo

```
POST /chat  {"message": "Agende a Maria para segunda às 14h"}
  -> analisador: intenção DADOS_OU_ACAO
  -> planejador (LLM): escolhe a ação e os argumentos
  -> código: valida os argumentos, resolve paciente, data e registro lendo a API Node
  -> resposta: resumo escrito pelo código + proposal.token (assinado, expira em 5 minutos)

POST /chat/confirm  {"proposal": "<token>"}   (cabeçalho Authorization: Bearer ...)
  -> código: verifica assinatura, validade e usuário
  -> código: relê o estado atual na API Node
  -> API Node: executa a escrita com o token do usuário
  -> resposta: mensagem montada pelo código a partir da resposta real da API
```

## Garantias

| Garantia | Como é obtida |
|---|---|
| A LLM nunca executa nada | Ela só escolhe a ação e os argumentos. A confirmação é um endpoint separado, sem LLM. |
| O resumo mostrado é fiel | É montado pelo código a partir dos registros reais lidos da API, não por texto da LLM. |
| A proposta não pode ser alterada nem lida | Token criptografado e autenticado (Fernet: AES-128 com HMAC-SHA256). Alterar qualquer caractere o invalida, e CPF e telefone não ficam legíveis em logs do gateway ou do navegador. |
| A proposta é do usuário que a pediu | O token guarda o identificador do usuário e é comparado com o do token de acesso na confirmação. |
| A proposta expira | Padrão de 5 minutos (`PROPOSAL_TTL_SECONDS`). |
| Autorização final | A API Node valida o token de acesso em toda chamada. Sem token válido, nada é escrito. |
| Repetir a confirmação é seguro | O estado é relido antes de escrever. Criar duplicado gera conflito, cancelar de novo é recusado e o pagamento só é alternado se a situação atual for diferente da pedida. |
| Ação inviável não é proposta | Paciente inativo, horário ocupado, agendamento inexistente ou já concluído, CPF inválido ou já cadastrado e dados fora das regras da API são detectados antes de propor. |
| Timeout em escrita | Não há nova tentativa automática. O usuário é orientado a conferir no aplicativo. |
| Texto malicioso não dispara ações | Texto de paciente, de histórico e da base nunca chega ao endpoint de confirmação. |

## Limites

- O pagamento é uma alternância na API. O assistente só a aciona quando a situação atual difere da pedida.
- A API não impede agendar em fim de semana ou em data passada. O resumo traz um aviso, e o usuário decide.
- `ASSISTANT_SIGNING_SECRET` deve conter pelo menos 32 caracteres, desconsiderando espaços nas extremidades. Se estiver ausente ou inválido, as ações ficam desabilitadas, sem geração de chave temporária; o serviço pode continuar atendendo o chat de leitura. Todos os processos precisam do mesmo segredo persistente. As flags são carregadas na inicialização e exigem reiniciar os processos para aplicar mudanças.
- Ações em lote ("cancele todos") não são suportadas.
- Reabrir atendimento, excluir definitivamente e registrar sessão avulsa não fazem parte desta etapa.
- Cadastrar paciente é uma conversa: o assistente lista o que falta (nome, CPF, telefone e valor da sessão), e o planejador junta os dados de todo o histórico enviado pelo cliente.
- Não há limite de pedidos por usuário nem registro de auditoria persistente. Os logs registram apenas a ação e o resultado, sem dados de pacientes.

## Dados pessoais nas operações de paciente

Ao cadastrar ou editar um paciente, os dados que o usuário digita (nome, CPF, telefone, e-mail, data de nascimento e valor da sessão) passam pelo provedor da LLM para serem extraídos, e permanecem no histórico enviado nos pedidos seguintes. As consultas de leitura nunca enviam CPF à LLM. Para desligar apenas as operações de paciente, use `PATIENT_ACTIONS_ENABLED=false`. Antes de usar com dados reais, o responsável pelo produto deve avaliar a base legal e o contrato com o provedor, nos termos da LGPD, por se tratar de dados de pacientes.
