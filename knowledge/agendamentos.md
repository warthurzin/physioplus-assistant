# Agendamentos

## Criar um agendamento
Um agendamento é criado para um paciente e exige data, horário de início e horário de término. A data usa o formato AAAA-MM-DD e os horários usam o formato HH:MM, por exemplo 08:00 e 09:00. Sem os campos obrigatórios o pedido é recusado.

## Atendimento domiciliar
O agendamento possui uma indicação de atendimento domiciliar, que informa se a consulta será realizada na casa do paciente.

## Conflito de horários
O sistema não permite marcar dois atendimentos no mesmo horário. Dois agendamentos que se sobreponham no mesmo dia são recusados com erro de conflito. Um agendamento das 08:30 às 09:30 conflita com outro das 08:00 às 09:00.

## Consultar e editar
Os agendamentos podem ser listados todos de uma vez, filtrados por data ou filtrados por paciente. Data, horários e atendimento domiciliar podem ser alterados depois da criação.

## Cancelar um agendamento
Somente agendamentos com situação agendada podem ser cancelados. Um agendamento já concluído não pode ser cancelado, e a tentativa resulta em operação não permitida. Depois de cancelado, o horário volta a ficar livre e pode receber um novo agendamento.

## Agendamentos e valores financeiros
Agendamentos programados não são contados como valores recebidos nem pendentes. O valor só entra no Financeiro quando existe uma sessão, ou seja, depois da confirmação do atendimento.