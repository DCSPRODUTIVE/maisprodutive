# MaisProdutive — integração experimental Yoosee

Objetivo: acessar câmeras próprias de locais distintos pelo navegador, sem VPN,
e posteriormente detectar pessoas e emitir alertas.

## Estado real

O painel implementa login e consulta de câmeras usando o protocolo identificado
por análise estática do instalador Windows **1.0.0.8 enviado pelo usuário**.
O executável não foi instalado ou executado. A implementação continua experimental:
nenhuma conta real foi autenticada nesta validação.

- Verificado: importação dos parâmetros do arquivo enviado, inicialização local,
  testes com respostas sintéticas e assinatura das consultas.
- Pendente: aceitação do login pelo serviço e listagem real das câmeras.
- Não implementado: transporte P2P de vídeo, reprodução no navegador, detecção de
  pessoas, notificações e hospedagem pública com autenticação.

O painel só lista câmeras recebidas da API. Uma lista de câmeras, por si só,
não confirma acesso ao vídeo.

## Preparar no Chromebook

Use o Terminal Linux. Se houver um servidor rodando, pressione **Ctrl+C** primeiro.
Execute os comandos abaixo, um por vez:

```sh
cd ~/maisprodutive
```

```sh
git pull origin main
```

```sh
sudo apt install -y 7zip
```

Mova o arquivo original **Yoosee-1.0.0.8.exe** para **Arquivos Linux**, se ainda não
estiver lá. Ele precisa ser o mesmo arquivo dividido e enviado para análise.
Não use o instalador 1.0.0.14 ou somente uma das partes.

```sh
python3 configure_desktop.py ~/Yoosee-1.0.0.8.exe
```

Espere a mensagem **Perfil Windows preparado**. A ferramenta verifica o SHA-256
do instalador e do executável interno, usa 7zip apenas para extração e grava os
parâmetros em `.local/yoosee-desktop.json`, ignorado pelo Git e com permissão 0600.
Não executa código Windows e não solicita senha da conta. Os hashes reconhecem o
arquivo analisado; não certificam a identidade do fabricante.

Se o original foi apagado e restaram as três partes, coloque-as em **Arquivos
Linux** e reconstrua primeiro, nesta ordem:

```sh
cat ~/Yoosee-parte-aa ~/Yoosee-parte-ab ~/Yoosee-parte-ac > ~/Yoosee-1.0.0.8.exe
```

Inicie o servidor:

```sh
python3 server.py --port 8081
```

Abra `http://localhost:8081` no Chrome do próprio Chromebook e recarregue a página.
O botão deve dizer **Testar login Windows**. Se mostrar o modo antigo, confira a
mensagem da importação e reinicie o processo do servidor.

Digite o e-mail e a senha usados na sua conta Yoosee. Para conta de telefone,
use somente números com DDD no login e o código do país separado (**55** para
Brasil). Faça uma tentativa e observe a resposta. Se o login for aceito, clique
em **Consultar câmeras**. Compartilhe somente a mensagem/código exibido, nunca
senha, perfil local, tokens ou resposta bruta.

Cada envio faz uma única tentativa, sem repetir automaticamente nem mudar para
outro protocolo após rejeição. O modo Windows tem prioridade quando o perfil
existe; um perfil inválido produz erro, sem fallback. Não é necessário obter
credenciais de desenvolvedor para testar este perfil importado.

## Desenvolvimento e validação

Python 3.10+ e biblioteca padrão, sem dependências Python. 7zip é necessário
somente para extrair o instalador; um `Yoosee.exe` interno com hash reconhecido
pode ser importado diretamente. Node.js serve apenas para testar a interface.

```sh
python -m unittest discover -s tests -v
node --test tests/test_web.cjs
python server.py --port 8080
```

São 46 testes Python e 6 testes de interface, com dados sintéticos. O perfil
padrão fica dentro do checkout; `YOOSEE_DESKTOP_PROFILE` permite indicar outro
caminho local. Não versione o perfil nem os binários do fabricante.

O servidor escuta apenas em loopback. O painel é uma bancada local; hospedagem
pública depende de HTTPS e autenticação adicionais. O GitHub armazena o código;
GitHub Pages não executa o servidor Python necessário à integração.

A senha é recebida pelo servidor local, transformada conforme o protocolo Windows
e enviada à API por HTTPS com verificação TLS. Não é gravada no projeto ou no
armazenamento do navegador. Sessões e tokens ficam em memória por até 20 minutos;
sair ou reiniciar o servidor apaga a sessão local, sem encerrar o aplicativo oficial.

## Rede e protocolos

Com perfil Windows, o painel usa `openapi-iot.cloudlinks.cn`. O teste de comunicação
consulta esse destino sem credenciais. Uma resposta HTTP ou um código de API
não autentica a conta. Sem perfil, o diagnóstico continua consultando os quatro
servidores históricos.

A API Windows usa POST JSON para `/openapi/app/user/login/account` e consulta
assinada GET para `/openapi/app/user/device/listDevice`. Parâmetros de aplicativo
são importados localmente do arquivo analisado. Certificados HTTPS continuam
verificados, mesmo que o executável original desative essa verificação.

Nesta máquina, o proxy ainda bloqueia o novo host com HTTP 403. Isso impede um
teste externo daqui, mas não determina o acesso à internet no Chromebook.
Salvar domínios no rascunho da configuração não aplica mudanças à máquina atual.

## Histórico do modo antigo

Sem perfil Windows, `YOOSEE_APP_ID` e `YOOSEE_APP_TOKEN` selecionam o cliente do SDK
histórico, quando ambos estão presentes. Sem ambos, permanece o modo antigo
`account-experimental`. Configuração parcial é erro. A tentativa real anterior
retornou `10901020` (parâmetros obrigatórios ausentes); isso não confirma senha
incorreta. O próximo teste deve usar o perfil Windows acima.

As opções históricas são `YOOSEE_PACKAGE` (padrão `com.yoosee`),
`YOOSEE_APP_VERSION` (padrão exploratório `00.00.00.01`) e `YOOSEE_API_HOST`
(padrão `api3.cloud-links.net`; também admite `api4.cloud-links.net`,
`api1.cloudlinks.cn` e `api2.cloudlinks.cn`). A CLI `python yoosee.py probe`
continua diagnosticando esses quatro hosts; `python yoosee.py devices` usa
somente o cliente antigo com `YOOSEE_USERNAME`/`YOOSEE_PASSWORD` no ambiente.
Use o painel para o novo protocolo Windows.

As evidências do SDK histórico, APK Android e análise Windows, com limites de
validação, estão em [docs/research.md](docs/research.md).
