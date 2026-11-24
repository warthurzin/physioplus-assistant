# Acesso e conta

## Cadastro e login
Para usar o PhysioPlus, o profissional cria uma conta com nome, e-mail e senha e depois entra com e-mail e senha. O cadastro exige a verificação de captcha. O login devolve um token de acesso e um token de renovação.

## Falhas de login e captcha
Depois de duas tentativas de login com senha incorreta, o sistema passa a exigir captcha no login seguinte. Sem o captcha, a tentativa é recusada com o código CAPTCHA_REQUIRED. A conta não é bloqueada por senhas incorretas: o captcha continua sendo exigido nos logins seguintes. Um login bem-sucedido com captcha zera o contador de falhas.

## Renovação e saída
O token de renovação permite obter um novo token de acesso sem digitar a senha novamente. Ao sair, o token de renovação é invalidado e deixa de funcionar.

## Recuperação de senha
Na recuperação de senha, o profissional informa o e-mail cadastrado e recebe uma mensagem com um link. O link abre a página de redefinição, onde são informadas a nova senha e a confirmação, que precisam ser iguais. O link vale para um único uso.

## Segurança da recuperação
A resposta da recuperação de senha é a mesma mesmo quando o e-mail não está cadastrado. Depois da redefinição, as sessões anteriores perdem a validade e a senha antiga deixa de funcionar.

## Exclusão da conta
A exclusão da conta exige que o profissional informe a senha atual e digite EXCLUIR para confirmar. Com senha incorreta, a conta permanece intacta. Com a senha correta, a conta é excluída de forma definitiva, junto com os pacientes, agendamentos, sessões e anotações vinculados a ela.