# Erros comuns e seus significados

## Dados inválidos
Quando um campo obrigatório falta, tem formato errado ou não é permitido, o sistema recusa o pedido como dados inválidos. Datas devem usar AAAA-MM-DD, horários devem usar HH:MM e CPFs precisam ser válidos.

## Não autenticado
Pedidos feitos sem estar autenticado são recusados. Nesse caso, é preciso entrar novamente no aplicativo.

## Não encontrado
O erro de não encontrado indica que o paciente, o agendamento, a sessão ou a anotação procurada não existe ou não está disponível para o profissional.

## Conflito
O erro de conflito aparece quando o pedido colide com algo que já existe, como um CPF já cadastrado, um horário padrão sobreposto ou um agendamento em horário ocupado.

## Operação não permitida
Este erro indica que o registro está em uma situação que não aceita a operação, como cancelar um agendamento concluído, confirmar um agendamento já concluído, desativar um paciente já inativo ou reativar um paciente já ativo.
