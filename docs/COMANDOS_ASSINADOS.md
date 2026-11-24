# Comandos Ed25519 — contrato v1

`app/actions/command_signer.py` implementa `AssistantCommandSigner`, correspondente
ao contrato de `physioPlus-backend/docs/ASSISTANT_SIGNED_COMMANDS.md` e ao verificador
`src/utils/assistantCommandVerifier.js` do Node.

O módulo é utilizado pelo `ActionService` na preparação de propostas Fernet v2.
O contrato dos bytes assinados permanece o mesmo; a integração operacional está em
[EXECUCAO_IDEMPOTENTE.md](EXECUCAO_IDEMPOTENTE.md).

## Interface e chave privada

```python
signer = AssistantCommandSigner(key_id="assistant-key-v1", private_key=private_key)
envelope = signer.sign(
    professional_id=professional_id,
    action="deactivate_patient",
    parameters={"patient_id": patient_id},
    preconditions={},
    ttl_seconds=300,
)
```

`private_key` deve ser um objeto `Ed25519PrivateKey` da biblioteca `cryptography`,
fornecido pelo chamador. PEM, bytes, strings, chaves públicas ou de outros algoritmos
são rejeitados. O módulo não gera chaves nem carrega arquivos, variáveis de ambiente,
credenciais ou configurações de produção. A integração lê `ASSISTANT_COMMAND_KEY_ID` e `ASSISTANT_COMMAND_PRIVATE_KEY` na configuração Python.
O segredo Fernet/JWT não é utilizado como chave Ed25519.

`clock`, opcional no construtor, permite injetar um relógio de teste que retorna
segundos Unix inteiros. Por padrão usa `int(time.time())`, lido uma vez por comando.

## Formato e bytes assinados

Cada chamada cria um UUID v4 novo e um JSON com exatamente:

- `version`: número `1`.
- `purpose`: `physioplus.assistant.execute`.
- `execution_id`: UUID v4 minúsculo gerado pelo assinador.
- `professional_id`: UUID minúsculo, versão 1 a 8 e variante RFC 4122.
- `action`: uma das oito ações do contrato Node.
- `issued_at`: segundos Unix inteiros positivos.
- `expires_at`: `issued_at + ttl_seconds`.
- `parameters` e `preconditions`: objetos JSON, inclusive vazios.

O JSON é serializado uma vez, em UTF-8 sem BOM, com `ensure_ascii=False`,
`allow_nan=False` e separadores `(',', ':')`. Os bytes resultantes são usados tanto
na assinatura quanto na codificação de `command`, sem reserialização posterior.

Assinatura Ed25519 pura, sem prehash externo, sobre:

```text
ASCII("PhysioPlus/assistant-command/v1") || 0x00 ||
ASCII(key_id) || 0x00 || command_bytes
```

No código Python:

```python
signed_bytes = (
    b"PhysioPlus/assistant-command/v1\x00"
    + key_id.encode("ascii")
    + b"\x00"
    + command_bytes
)
signature = private_key.sign(signed_bytes)
```

O resultado tem exatamente os campos string `key_id`, `command` e `signature`.
Os dois últimos são base64url canônico sem padding; a assinatura decodificada tem
64 bytes. A assinatura vincula também o `key_id`.

## Limites e erros

O assinador exige TTL inteiro entre 1 e 300 segundos, timestamps até
`Number.MAX_SAFE_INTEGER` e comando serializado de no máximo 16384 bytes. O limite
de bytes é aplicado durante a serialização, antes de assinar.

Para parâmetros e precondições, aplica os limites estruturais do Node: profundidade
máxima 8 (raiz 0), até 64 propriedades por objeto, nomes
`[A-Za-z][A-Za-z0-9_]{0,63}`, strings de até 2048 unidades UTF-16 e arrays de até
100 itens. Aceita somente dict, list, str, int, float finito, bool e None; números
devem ter módulo de até `Number.MAX_SAFE_INTEGER`. Rejeita propriedades reservadas
`__proto__`, `prototype`, `constructor`, referências cíclicas, NaN, Infinity, tipos
não JSON e surrogates Unicode isolados. Valida também um orçamento total de nós
para interromper estruturas que já não poderiam caber no limite de bytes.

`key_id` segue `[A-Za-z0-9][A-Za-z0-9._-]{0,63}`. Versão e finalidade são fixas;
o chamador não pode sobrescrevê-las. As verificações são estruturais e não validam
campos de negócio específicos para cada ação.

Falhas previstas lançam `AssistantCommandSigningError`, com código e mensagem
fixos: `INVALID_KEY`, `INVALID_KEY_ID`, `INVALID_COMMAND`, `INVALID_TIME` ou
`COMMAND_TOO_LARGE`. O módulo não produz logs nem imprime chaves, assinaturas ou
comandos.

## Prova de interoperabilidade reproduzível

Na raiz do repositório Python, com as dependências existentes e Node disponíveis:

```powershell
.\.venv\Scripts\python.exe -B -m scripts.check_command_signer --node-backend "<caminho-do-physioPlus-backend>"
node --check scripts/assistant_command_bridge.cjs
```

`--node-backend` aceita caminho relativo ao diretório corrente ou absoluto.
`--node-executable` permite informar outro executável Node. Não há caminho local
absoluto gravado na implementação. Ausência do backend/verificador ou do Node
interrompe a execução; os testes entre linguagens não são omitidos silenciosamente.

A suíte unittest gera chaves Ed25519 temporárias exclusivamente em memória. As
chaves privadas não são enviadas ao Node nem gravadas em arquivos. A ponte
`scripts/assistant_command_bridge.cjs` recebe dados sintéticos por stdin e importa
o verificador real do backend por caminho explícito. Bloqueia outras dependências,
exceto `node:crypto` e `node:util`, durante o carregamento e uso do verificador.
Não carrega app, banco, rotas, configuração global ou `.env`.

A saída da ponte contém apenas aceitação, códigos de erro e indicadores booleanos
de igualdade dos bytes/UTF-8; não registra os comandos ou assinaturas. A suíte
compara os bytes montados em Python aos montados em Node e verifica a assinatura
sobre esses mesmos bytes com o `crypto` nativo.

Fixtures inválidas são assinadas diretamente com `cryptography` apenas nos testes
negativos, para provar que o Node rejeita versão, finalidade e prazos incompatíveis.
O assinador público continua impedindo a produção desses formatos.

## Limitações preservadas

O Node continua sendo a autoridade sobre identidade autenticada e validade ao
receber o comando: a execução nova não aceita expiração; a consulta pode ler um comando
expirado somente para recuperar comprovante terminal anterior.
O assinador não conhece o relógio remoto nem autentica o identificador recebido.

O assinador isolado não executa nem autoriza negócio. `ActionService` chama `sign()`
uma vez por proposta e conserva o envelope Fernet v2; o coordenador Node implementa
a execução idempotente com comprovante durável. Chamar `sign()` novamente geraria
outro `execution_id` e não é usado para repetir uma confirmação.

Gestão, armazenamento seguro e rotação de chaves de produção ficam para entregas
posteriores. Nenhuma assinatura válida autoriza por si só uma operação de negócio.
