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
Um novo acesso começa um novo ciclo, sem recuperar o minuto exato de uma janela
anterior. Economia desativada pelo botão é salva como desativada.

Reports agora mostra e grava somente pessoas detectadas. Registros antigos de
abertura e veículos ficam ocultos, sem apagar o banco de dados.


Reports oferece Fotos e Vídeos. Apenas câmeras com **Detectar pessoas** ativado
produzem esses registros. As fotos duram até 30 dias (máximo 1.000 por conta), e
os vídeos de até dois minutos duram até 5 dias. Gravar não abre uma conexão extra
com a câmera. Pausa de economia, desligamento ou desativação encerra o clipe com o
trecho disponível; não prolonga o consumo de 4G.
