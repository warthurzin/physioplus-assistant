ACTION_CLARIFY_MESSAGE = (
    "Para fazer isso preciso de todos os dados: o paciente, o dia e, para agendar, o horário de início. "
    "Para marcar um pagamento, informe também se é paga ou pendente. Pode me passar o que falta?"
)
ACTIONS_UNAVAILABLE_MESSAGE = (
    "Ainda não consigo alterar dados por aqui. Posso explicar como fazer isso no aplicativo."
)
CONFIRM_SUFFIX = "Confirma? Use o botão Confirmar. A proposta expira em {minutes} minutos."

PATIENT_NOT_FOUND = "Não encontrei nenhum paciente com o nome informado."
PATIENT_AMBIGUOUS = "Encontrei mais de um paciente com esse nome: {names}. Qual deles você quer?"
PATIENT_INACTIVE = "{name} está inativo. Reative o paciente no aplicativo antes de {verb}."
SLOT_TAKEN = "Já existe um agendamento nesse horário: {name}, das {start} às {end}. Escolha outro horário."
END_OVERFLOW = "O horário de término passaria da meia-noite. Informe um horário de início e de término no mesmo dia."
NO_APPOINTMENT = "Não encontrei agendamento ativo de {name} em {date}."
MANY_APPOINTMENTS = "{name} tem mais de um agendamento em {date}, às {times}. Informe o horário."
NO_SESSIONS = "{name} não tem sessões registradas."
NO_SESSION_ON_DATE = "Não encontrei sessão de {name} em {date}."
PAYMENT_ALREADY = "A sessão de {name} já está {label}. Nada a alterar."
MANY_SESSIONS = "{name} tem mais de uma sessão {label_opposite}: {dates}. Informe o dia."

WEEKEND_WARNING = " Atenção: a Agenda do PhysioPlus só exibe dias úteis."
PAST_WARNING = " Atenção: essa data já passou."

AUTH_EXPIRED = "Não consegui validar a sua sessão. Entre novamente no aplicativo e tente de novo."
PROPOSAL_EXPIRED = "Essa proposta expirou. Peça a ação de novo para gerar uma nova."
PROPOSAL_INVALID = "Essa proposta não é válida para a sua conta. Nada foi alterado."
RECORD_GONE = "Não encontrei mais esse registro. Nada foi alterado."
SLOT_NOW_TAKEN = "Esse horário já está ocupado por outro agendamento. Nada foi alterado."
REJECTED = "O sistema recusou a operação: {detail}. Nada foi alterado."
REJECTED_GENERIC = "O sistema recusou a operação. Nada foi alterado."
WRITE_UNCERTAIN = (
    "Não consegui confirmar se a operação foi concluída. Verifique no aplicativo antes de tentar de novo."
)

CREATED = "Agendamento criado: {name}, {date}, das {start} às {end}."
CANCELLED = "Agendamento de {name} em {date} cancelado."
CONFIRMED = "Atendimento de {name} em {date} confirmado. A sessão foi criada com pagamento pendente ({value})."
PAYMENT_DONE = "Sessão de {name} de {date} marcada como {label}."
PAYMENT_NO_CHANGE = "A sessão de {name} de {date} já estava {label}. Nada foi alterado."

PATIENT_MISSING = "Para cadastrar o paciente ainda falta: {fields}. Envie esses dados e eu preparo o cadastro."
PATIENT_INVALID = "Não consegui preparar essa operação: {errors}."
PATIENT_CPF_EXISTS = "Já existe um paciente com esse CPF: {name}. Nada foi alterado."
PATIENT_NOTHING_TO_CHANGE = "Esses dados já são os atuais de {name}. Nada a alterar."
PATIENT_NO_CHANGES_GIVEN = "Informe o que você quer alterar em {name}, por exemplo o telefone ou o valor da sessão."
PATIENT_ALREADY_INACTIVE = "{name} já está inativo. Nada a alterar."
PATIENT_ALREADY_ACTIVE = "{name} já está ativo. Nada a alterar."
PATIENT_CPF_CONFLICT = "Já existe um paciente com esse CPF. Nada foi alterado."
PATIENT_DEACTIVATE_SUMMARY = (
    "Desativar o paciente {name}. Ele passa para a lista de inativos, deixa de receber novos "
    "agendamentos e o histórico é mantido."
)
PATIENT_REACTIVATE_SUMMARY = "Reativar o paciente {name}. Ele volta para a lista de ativos."
PATIENT_CREATED = "Paciente {name} cadastrado."
PATIENT_UPDATED = "Dados de {name} atualizados."
PATIENT_DEACTIVATED = "Paciente {name} desativado."
PATIENT_REACTIVATED = "Paciente {name} reativado."