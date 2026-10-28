# Acesso externo protegido no Chromebook

O servidor continua no computador que já executa as câmeras. `remote_access.py`
publica somente o painel por um túnel HTTPS Cloudflare, sem abrir portas no
roteador nem instalar VPN nos locais das câmeras. Não hospeda o processamento
na nuvem. O computador e o terminal precisam permanecer ligados.

## Instalação

Pare o servidor antigo com Ctrl+C. No Terminal Linux x86_64/amd64 do Chromebook,
um comando por vez:

```sh
cd ~/maisprodutive
```

```sh
git pull origin main
```

```sh
wget -O /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
```

```sh
sudo dpkg -i /tmp/cloudflared.deb
```

```sh
python3 remote_access.py --port 8097
```

Na primeira execução, informe a senha de acesso que deseja usar (a senha não
aparece ao digitar). Use a senha indicada na conversa, caso queira mantê-la.
O programa salva somente um hash com salt em `.local/access.json`, fora do Git.
A mesma senha será exigida ao abrir o sistema localmente nessa instância ou pelo
endereço externo. Depois da senha do sistema, entre na sua conta Yoosee para
abrir suas câmeras. O sistema não salva a senha da Yoosee.

O terminal exibirá um endereço como `https://nome-aleatorio.trycloudflare.com`.
Abra **o endereço exibido no seu terminal** pelo celular, inclusive fora do Wi-Fi.
O endereço é temporário e muda ao reiniciar o túnel. O Cloudflare Quick Tunnel
não exige conta, mas depende da disponibilidade e das limitações do serviço.

Para usar o mesmo servidor no Chromebook, abra `http://localhost:8097`. Para
encerrar acesso externo, pressione Ctrl+C no terminal; servidor, streams e túnel
são encerrados. Não execute vários servidores concorrentes no mesmo diretório.

## Trocar senha e endereços permanentes

Com o servidor parado:

```sh
python3 configure_access.py
```

Reinicie `remote_access.py` para invalidar as sessões anteriores e usar a nova
senha. A sessão de entrada dura até 12 horas sem uso e se renova enquanto o painel
é acessado. Há limite global de cinco tentativas de entrada por minuto.

Para um domínio HTTPS permanente com proxy/túnel já configurado no próprio
computador, use `python3 server.py --port 8097 --public-origin https://seu-dominio`.
É obrigatório preparar a senha antes. O proxy deve preservar Host, encaminhar
`X-Forwarded-Proto: https`, terminar TLS e acessar somente 127.0.0.1:8097.
Nenhuma origem arbitrária ou HTTP externo é aceita. O modo local protegido,
sem túnel, usa `python3 server.py --port 8097 --protected`.

## Câmeras e preferências

Cada navegador possui sua própria sessão de conta Yoosee. O limite de 12 conexões
é global por servidor, compartilhado pelos acessos. Abrir as mesmas câmeras em
dois dispositivos pode consumir conexões e dados adicionais. A capacidade real
depende de CPU, memória, rede e SDK, não apenas da opção de mosaico.

O mosaico 8/12 e as câmeras em Economia de dados/Detectar pessoas ficam no banco local, separados
por login da conta Yoosee. Ao entrar novamente, inclusive por outro navegador,
essas escolhas são recuperadas. Parar cancela o agendamento atual, mas conserva
a preferência; Assistir ou um novo acesso volta a aplicar o modo escolhido.
Nas câmeras com detecção, reabrir o painel preserva o ciclo mantido no servidor.
Após reiniciar o servidor e fazer login, começa um novo ciclo. Economia desativada pelo botão é salva como desativada.

Reports agora mostra e grava somente pessoas detectadas. Registros antigos de
abertura e veículos ficam ocultos, sem apagar o banco de dados.


Reports oferece Fotos e Vídeos. Apenas câmeras com **Detectar pessoas** ativado
produzem esses registros. As fotos duram até 30 dias (máximo 1.000 por conta), e
os vídeos de até dois minutos mais até cinco segundos anteriores duram até 15 dias.
A gravação local reutiliza os quadros existentes. A busca experimental no cartão
pode abrir uma conexão adicional, quando há uma vaga e tempo na janela ativa, e
só substitui o local após validar horário e arquivo. Pausa de economia, desligamento ou desativação encerra o clipe com o
trecho disponível; não prolonga o consumo de 4G.

## Iniciar servidor e túnel automaticamente no Linux

Para o túnel permanente `torre-dcs` e o domínio já configurado
`https://cameras.maisprodutive.com.br`, o instalador cria dois serviços systemd.
Eles iniciam quando o Linux inicia, usam seu usuário habitual e reiniciam em caso
de falha. Não usam o túnel temporário e não dependem de terminais abertos.

Primeiro pare os dois processos manuais com Ctrl+C em seus terminais. Execute
um comando por vez, sem colocar sudo antes de python3:

```sh
cd ~/maisprodutive
```

```sh
git pull origin main
```

```sh
python3 configure_startup.py --install
```

O comando prepara os arquivos em `.local/startup`, verifica senha de entrada e
configuração do túnel e solicita sudo somente para instalar os serviços do Linux.
Não pede nem salva senha da Yoosee, token do túnel ou senha do painel. A instalação
usa a senha de painel em `.local/access.json` e o túnel em
`~/.cloudflared/config.yml`, que já precisam estar configurados.

Confira o resultado:

```sh
systemctl is-active dcs-control.service dcs-tunnel.service
```

Devem aparecer duas linhas `active`. Depois disso pode fechar os terminais e
abrir o endereço fixo. Não execute também os comandos manuais ou remote_access.py
na mesma porta. Se aparecer erro, compartilhe apenas a mensagem, sem arquivos de
credenciais ou tokens.

**No Chromebook:** esses serviços iniciam dentro do ambiente Linux. Eles não
podem forçar o ChromeOS a iniciar a máquina Linux após ligar o computador. Se o
Linux não iniciar automaticamente no seu aparelho, abra o aplicativo Terminal
uma vez; depois os serviços iniciam sem comandos. Não há mudança no endereço fixo.
A aba só precisa ficar aberta para visualizar. O servidor executa os ciclos das
câmeras com Detectar pessoas habilitado mesmo quando o navegador está fechado. O login Yoosee continua necessário após reiniciar o servidor: as sessões
são mantidas em memória e a senha da conta não é armazenada. Após esse login inicial, a página pode ser fechada. O instalador não
promete iniciar a VM Linux nem autenticar na Yoosee automaticamente ao ligar o ChromeOS.

Para aplicar uma atualização de código aos serviços, após git pull:

```sh
sudo systemctl restart dcs-control.service dcs-tunnel.service
```

Para consultar uma falha do sistema:

```sh
systemctl status dcs-control.service dcs-tunnel.service --no-pager
```

Para desfazer a inicialização automática, sem apagar configurações ou Reports:

```sh
python3 configure_startup.py --uninstall
```

Se o Linux não estiver executando systemd, o instalador informa isso e não instala
serviços. Nesse caso, é necessário adaptar a inicialização ao ambiente mostrado
pelo aparelho; não substitua isso por comandos que executem o sistema como root.


## Monitorar em segundo plano

Após atualizar, reinicie os serviços e faça login no painel uma vez. Câmeras com
**Detectar pessoas** habilitado ficam sob controle do servidor. O navegador pode
ser fechado; as câmeras com Economia conectam por 5 minutos e pausam por 25, sem
que reabrir o site altere esse ciclo. O último quadro aparece como pausado.

**Parar** e fechar a aba encerram somente a visualização. Para encerrar a análise,
desative **Detectar pessoas**, clique no botão **Sair da conta** dentro do painel
ou pare o serviço DCS. A autorização é mantida só em memória; reiniciar o serviço
ou uma invalidação da Yoosee pode exigir novo login. Não é necessário manter o
site aberto no computador servidor após o primeiro login.
