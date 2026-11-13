# Consulta e edição de pacientes

## Listar e buscar
A lista de pacientes mostra por padrão os pacientes ativos. É possível listar os inativos e buscar por nome ou por CPF. O perfil completo de um paciente é consultado pelo seu identificador, e um identificador inexistente resulta em erro de paciente não encontrado.

## Editar dados
A edição aceita alterar apenas os campos desejados, como telefone ou valor da sessão. Uma edição sem nenhum campo é recusada. Informar o mesmo CPF que o paciente já possui não causa erro, mas usar o CPF de outro paciente gera conflito.

## Desativar paciente
Desativar um paciente não apaga seus dados. O paciente passa a constar na lista de inativos e o histórico é mantido. Desativar um paciente que já está inativo é uma operação não permitida.

## Reativar paciente
Um paciente inativo pode ser reativado e volta para a lista de ativos. Reativar um paciente que já está ativo é uma operação não permitida.
