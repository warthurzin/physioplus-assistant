# Cadastro de pacientes

## Dados obrigatórios
Para cadastrar um paciente são obrigatórios o nome completo, o CPF, o telefone e o valor da sessão. Sem algum desses campos o cadastro é recusado.

## Dados opcionais
Também podem ser informados RG, data de nascimento, e-mail e endereço. A data de nascimento usa o formato AAAA-MM-DD. O endereço é composto por CEP, rua, número e bairro.

## CEP e endereço
O CEP pode preencher o endereço automaticamente como auxílio. A rua e o bairro podem ser editados depois do preenchimento, e o número é sempre informado manualmente. O cadastro não possui campos de cidade nem de estado.

## CPF do paciente
O CPF precisa ser válido, e números como 111.111.111-11 são recusados. Não é possível cadastrar dois pacientes com o mesmo CPF, e a tentativa de duplicar gera um erro de conflito.

## Valor da sessão
O valor da sessão cadastrado no paciente é o valor padrão para os próximos atendimentos. Alterar esse valor não muda o valor das sessões já registradas, que guardam o seu próprio valor histórico.
