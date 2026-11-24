# Pagamento de sessões

## Como o pagamento é registrado
O pagamento é registrado em cada sessão. A operação de pagamento funciona como alternância: ao ser executada, marca a sessão como paga, e ao ser executada de novo, desfaz o pagamento.

## Cuidado com repetições
Por ser uma alternância, repetir a operação desfaz o resultado anterior. Antes de alterar o pagamento, é importante conferir a situação atual da sessão. Em caso de dúvida sobre o resultado, consulte o estado da sessão antes de tentar novamente.

## Pagamento e realização
Pagamento e realização são coisas diferentes. Uma sessão pode ter sido realizada e continuar com pagamento pendente, e o valor pendente aparece no resumo financeiro. Quando um agendamento é confirmado, a sessão criada fica no Financeiro com pagamento pendente até ser marcada como paga.

## Sessões excluídas
Não é possível alterar o pagamento de uma sessão que já foi excluída, e a tentativa resulta em erro.