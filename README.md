# Torre de Controle DCS

Central de monitoramento no navegador para câmeras próprias Yoosee de diferentes
locais, sem VPN. O repositório continua em `DCSPRODUTIVE/maisprodutive`.

## Estado real

- **Confirmado pelo usuário no Chromebook:** login, consulta de oito câmeras e
  captura de imagens reais na maioria delas.
- **Nesta versão:** layout responsivo, mosaico com seleção de 8 ou 12 transmissões
  independentes, busca por nome, tela cheia, modo foco, captura e parada individual
  ou de todas as câmeras. Transmissão experimental de até cinco imagens/s por
  câmera, sem áudio, com conexão P2P mantida aberta.
- **Formato 5:** o adaptador aceita tanto três planos YUV420 entregues pelo
  decodificador H.265 quanto NV12 de dois planos, com validação dos buffers.
- **Conexão e qualidade:** login consulta as câmeras e abre o mosaico; cada câmera
  oferece Equilibrada, SD original, HD e FHD. A interface mostra as dimensões
  recebidas no JPEG. HD/FHD dependem do suporte e da resposta de cada câmera.
- **Confirmação real:** o usuário mostrou transmissões reais em parte do mosaico.
  A correção dos buffers e os novos modos HD/FHD ainda precisam ser testados nas
  câmeras que falhavam; testes sintéticos não substituem essa confirmação.
- **Reports:** fotos de detecção local de pessoas, sem registros de abertura de câmera.
  Requer instalar o modelo e OpenCV conforme abaixo. Alertas externos não estão ativos.
- **Economia de dados:** por câmera, 5 minutos conectada e 25 pausada, preservando
  o último quadro. As demais câmeras continuam independentes. Acesso remoto protegido por túnel HTTPS disponível. Áudio, PTZ e gravação contínua não estão implementados.

A interface não contém câmeras ou vídeos simulados. Só apresenta dispositivos da
conta e imagens recebidas pelo adaptador. Fixtures usadas nos testes não fazem
parte do painel publicado.

## Atualizar uma instalação já preparada

No Terminal Linux do Chromebook, pare o servidor com **Ctrl+C**. Execute um
comando por vez:

```sh
cd ~/maisprodutive
```

```sh
git pull origin main
```

```sh
python3 configure_video.py ~/Yoosee-1.0.0.8.exe --update
```

A atualização recompila o adaptador nativo. O perfil de login é preservado e a
versão anterior íntegra fica em `.local/video-backup-*`. Arquivos desconhecidos
ou alterações inesperadas bloqueiam a troca, sem apagar a instalação existente.

```sh
python3 server.py --port 8094
```

Abra `http://localhost:8094` no Chrome do próprio Chromebook. Conecte sua conta: as câmeras são consultadas e o mosaico abre automaticamente.
Use **Assistir** para reabrir uma câmera ou **Assistir todas** para abrir o mosaico. Esse último ativa o **Modo foco**, que prioriza os vídeos;
**Visão completa** devolve o cabeçalho e a área da conta. Use **Parar**, **Parar
todas**, **Capturar**, busca pelo nome e o botão de tela cheia em cada imagem.

Os estados **Conectando**, **Ao vivo**, **Aguardando** e **Atenção** são calculados
pelos dados recebidos. Uma imagem antiga deixa de contar como ao vivo após três
segundos sem atualização. Falha em uma câmera não encerra as outras. Falhas transitórias de transmissão são retentadas com espera progressiva de 5 a
60 segundos, sem repetir o login. Parar/Parar todas cancela as tentativas. Compartilhe somente a mensagem de
erro exibida, nunca senha, perfil, tokens ou saídas brutas do SDK.

## Primeira preparação no Chromebook

Requer Linux x86_64/amd64 e Python 3.10+. As ferramentas nativas podem levar alguns
minutos para instalar:

```sh
sudo apt install -y --no-install-recommends 7zip wine gcc-mingw-w64-x86-64 ffmpeg
```

Coloque o instalador original **Yoosee-1.0.0.8.exe** em **Arquivos Linux**.
Somente o arquivo exato enviado para análise é aceito; renomear outra versão não
funciona. Se só restaram as partes, reconstrua primeiro:

```sh
cat ~/Yoosee-parte-aa ~/Yoosee-parte-ab ~/Yoosee-parte-ac > ~/Yoosee-1.0.0.8.exe
```

Prepare o perfil e o adaptador a partir do diretório do projeto:

```sh
python3 configure_desktop.py ~/Yoosee-1.0.0.8.exe
```

```sh
python3 configure_video.py ~/Yoosee-1.0.0.8.exe
```

O primeiro comando importa parâmetros estáticos do cliente para
`.local/yoosee-desktop.json` (permissão 0600). O segundo extrai quatro DLLs com
hashes conhecidos e compila o código C deste projeto para `.local/video`.
Esses dois comandos não executam o SDK e não pedem a senha da conta. Os hashes
reconhecem o arquivo inspecionado; não certificam a identidade do fabricante.
O adaptador executa a biblioteca Windows pelo Wine quando você solicita imagem
ou transmissão. Os binários do fabricante não são distribuídos pelo repositório.

Faça login pelo formulário local, com o e-mail e a senha da sua conta Yoosee.
Para telefone, informe apenas os números com DDD, e país separado (**55** para
Brasil). O botão indica **Entrar** e o formulário desaparece após autenticar. Se aparecer o modo antigo,
confira a importação do perfil e reinicie o processo do servidor.

## Operação e limites

Há até doze conexões nativas simultâneas no servidor, cada uma com um processo do
SDK Wine e um conversor FFmpeg. No máximo duas câmeras iniciam a conexão ao mesmo
tempo; as demais aparecem como **Na fila** até que uma abertura termine ou receba
o primeiro quadro. Depois de conectadas, as doze podem continuar transmitindo.
A espera na fila não consome os 45 segundos de tentativa do primeiro quadro.
Todos os pools de threads do FFmpeg são limitados. A prévia do mosaico tem até
640 pixels de largura; a abertura individual mantém até 960 pixels em **Equilibrada**.
**SD original** mantém o fluxo SD sem redução local. **HD** e **FHD** solicitam esses
perfis ao SDK e preservam a resolução entregue, com JPEG de maior qualidade.
Para melhor imagem, selecione **FHD · sem redução** no canto da imagem e use tela
cheia. Se não funcionar naquela câmera, teste **HD**. A troca reinicia somente
essa câmera. Confira **Imagem: largura × altura** abaixo do vídeo: escolher FHD
não garante 1920×1080, pois o dispositivo/provedor pode entregar outra resolução.
O mosaico começa pelas primeiras 8 ou 12 câmeras, conforme a seleção da conta. Consumo de CPU, memória e internet cresce com as câmeras abertas. Não há
alteração automática de qualidade; a preferência escolhida dura até recarregar a página.

A conexão é reutilizada para os quadros seguintes; não se abre um login a cada
imagem. O painel recebe somente o JPEG mais recente de cada câmera, sem acumular
um histórico. **Capturar** reaproveita um quadro da transmissão quando ela já está
aberta. Uma captura sem transmissão abre um processo pontual.

As câmeras **sem Detectar pessoas** continuam dependendo da visualização e param
após 20 segundos sem consultas ou ao fechar a página. As câmeras **com Detectar
pessoas** são controladas pelo servidor e seguem ativas em segundo plano,
independentemente de aba, cookie ou sessão do navegador. **Parar** e **Parar todas**
encerram apenas suas visualizações. Para parar o monitoramento, desative Detectar
pessoas, use **Sair da conta** ou encerre o serviço.

A sessão de navegação expira após 20 minutos sem uso, mas isso não cancela o
monitoramento já autorizado. Após expirar, entre novamente para ver o painel e os
Reports. O servidor guarda a autorização da Yoosee somente em memória; reinício
do serviço ou invalidação pelo provedor exige novo login. Sem primeiro quadro em
45 segundos ou sem novos quadros por 8 segundos, a conexão é encerrada e o
servidor tenta novamente, respeitando a janela de economia. A captura pontual tem
limite próprio e não abre uma câmera monitorada durante a pausa de economia.

Tokens passam pela entrada padrão do adaptador, sem argumentos de shell, logs
ou respostas ao navegador. Senhas da conta não são gravadas. Sessões e imagens
ficam em memória. O SDK trabalha em diretório temporário privado, removido após o
processo; o prefixo Wine local persiste em `.local/wine-video`. O perfil de login,
os binários e os backups locais são ignorados pelo Git.

Cada operação de vídeo exige cookie de sessão, Origin correspondente e CSRF.
Somente IDs da última consulta bem-sucedida da conta são aceitos. Identificadores
locais de transmissão evitam que respostas atrasadas parem uma nova conexão.

O servidor escuta apenas em loopback. Hospedagem pública depende de HTTPS e
controle de acesso adicionais. GitHub armazena o código; GitHub Pages não executa
o servidor Python e o SDK necessários à integração.

## Desenvolvimento e verificação

Python usa somente a biblioteca padrão. Node.js é necessário apenas para testes
da interface. Parte dos testes de pipeline usa FFmpeg local e quadros sintéticos.

```sh
python -m unittest discover -s tests -v
node --test tests/test_web.cjs
python server.py --port 8080
```

71 testes Python e 16 de interface passaram. Também foram exercitados o binário
nativo no Wine sem rede, o pipeline com quadros contínuos sintéticos e a interface
no Chromium em desktop/Chromebook e celular. Esses resultados não validam oito
conexões reais simultâneas. `YOOSEE_DESKTOP_PROFILE` permite indicar outro caminho
local para o perfil. Nunca versione seus valores nem os binários do fabricante.

## Protocolos e histórico

O perfil Windows usa `openapi-iot.cloudlinks.cn`: POST JSON para
`/openapi/app/user/login/account` e GET assinado para
`/openapi/app/user/device/listDevice`, sempre com verificação TLS. A transmissão
usa a biblioteca `IotVideoSDK.dll` do instalador analisado, em processo separado.
Uma resposta no teste de comunicação comprova apenas acesso ao endpoint.

Sem perfil, permanece o SDK histórico: ambos `YOOSEE_APP_ID`/`YOOSEE_APP_TOKEN`
selecionam o cliente antigo; configuração parcial é erro; ausência de ambos
seleciona `account-experimental`. Esse último retornou `10901020` no teste anterior,
por parâmetros obrigatórios ausentes. O perfil Windows resolveu a autenticação.
A CLI `python yoosee.py probe`/`devices` continua usando somente o protocolo antigo.
Use o painel para Windows e vídeo. O proxy desta nuvem bloqueia o novo host HTTP;
o teste real bem-sucedido ocorreu na conexão do Chromebook.

Evidências, hashes e investigação em [docs/research.md](docs/research.md).

## Uso contínuo na TV

Mantenha o servidor ativo no computador ligado à TV por HDMI. A página só precisa
ficar aberta para visualizar; o monitoramento habilitado continua sem ela.
O painel renova a sessão local enquanto aberto e tenta recuperar transmissões
após quedas, sem guardar senha nem repetir o login. Cada processo nativo ainda
possui o limite de 20 minutos; o painel abre outra conexão após esse encerramento,
com uma breve interrupção. Parar uma câmera ou todas cancela as tentativas.
Use tela cheia do Chrome e configure o Chromebook para não suspender nem apagar
a tela enquanto estiver na tomada. Uma aba congelada pelo navegador não consegue
manter o monitoramento. Não feche a tampa se isso suspender o computador.

Esta versão conserva a sessão em memória: reiniciar o servidor/computador ou
uma invalidação do token pela Yoosee pode exigir novo login. Não há promessa de
funcionamento ininterrupto nem recuperação de autenticação sem credenciais.

## Reports: instalar detecção e registrar eventos

Depois de atualizar o código, no Terminal Linux do Chromebook:

```sh
sudo apt install -y python3-opencv python3-numpy
```

```sh
python3 configure_reports.py
```

```sh
python3 server.py --port 8096
```

Abra http://localhost:8096, entre e mantenha as câmeras transmitindo. **Reports ↗**
abre outra aba sem interromper o monitoramento. A instalação baixa uma única vez
aproximadamente 23 MB do MobileNet-SSD público, em revisão fixa e com SHA-256
verificado; imagens das câmeras não são enviadas para IA externa. Sem instalação,
a página explica que a detecção está inativa; nenhuma abertura de câmera é registrada.
O modelo pode gerar falsos positivos/negativos; não determina identidade.

Ative **Detectar pessoas** em cada câmera desejada; o padrão é desativado.
A escolha é salva por conta, junto com Economia de dados e o mosaico. Somente
as câmeras habilitadas produzem fotos e vídeos. A análise usa o último quadro recente, a cada 1 segundo por câmera, conforme a capacidade do servidor.
A presença contínua gera uma foto a cada 30 segundos; uma nova aparição após
ausência pode gerar outra após 5 segundos. Esse intervalo não identifica se uma pessoa é diferente da anterior;
pessoas que passam rapidamente podem não aparecer entre as amostras. Apenas a
classe pessoa é utilizada. Não há detecção de veículos, leitura de placas nem
identificação facial. Registros antigos de veículos e de abertura de câmeras ficam ocultos em Reports,
sem apagar o banco existente. O modelo instalado anteriormente pode ser reutilizado.

Fotos, horário, câmera, caixas e confiança ficam em `.local/reports/events.sqlite3`,
com acesso pelo painel autenticado e separação por conta. As credenciais Yoosee não são
salvas. O token Telegram, se configurado, é salvo neste banco privado. Retenção de fotos: até 1.000 registros por conta e 30 dias. Uma rotina
de manutenção remove os expirados enquanto o servidor está ligado. O arquivo de banco pode ocupar espaço mesmo após expirar registros;
SQLite reutiliza essas páginas. Faça backup desse diretório se desejar preservar
os registros. A pausa de economia e desativar Detectar pessoas interrompem novos eventos; Parar apenas encerra a visualização das câmeras monitoradas em segundo plano.

Em **Reports**, as abas **Fotos** e **Vídeos** separam os registros. Uma detecção
inicia um MP4 H.264 de até 120 segundos, sem áudio, com alvo de 10 quadros/s, reutilizando os
JPEGs da conexão existente. Não abre outra conexão P2P. Cada câmera pode ter um
clipe em andamento; enquanto grava, novas detecções não criam vídeos sobrepostos.
Depois de concluir, outra detecção pode iniciar outro vídeo. Falhas têm intervalo
mínimo de 60 segundos antes de nova tentativa de gravação.

Os vídeos ficam em `.local/reports/videos`, com metadados privados no banco.
São excluídos após 15 dias por manutenção periódica (a cada minuto com servidor
ligado) e ao acessar o armazenamento. Após desligamento, a limpeza ocorre na
próxima inicialização. Encerrar a conexão, perder conexão, desativar detecção ou entrar na pausa
de economia encerra o clipe no trecho disponível, identificado **trecho parcial**.
O sistema não prolonga a janela 4G para completar dois minutos. Ao reiniciar o
servidor, gravações interrompidas ficam como falha, sem disponibilizar MP4 incompleto.

Para limitar consumo local, os encoders usam uma thread, largura máxima de 1920
pixels, e cada arquivo é limitado a aproximadamente 96 MB durante a captura.
Novas gravações são recusadas com menos de 256 MB livres; o Reports informa a
falha de espaço. Essa proteção não substitui conferir o armazenamento. Fotos
apagadas liberam páginas reutilizáveis no SQLite; vídeos expirados são removidos
do disco. O vídeo gravado é uma amostragem do fluxo recebido, não o stream original
da câmera.

## Economia de dados em câmeras 4G

Clique em **Economia de dados** na câmera desejada. O primeiro ciclo começa
imediatamente: até 5 minutos conectada, seguidos de 25 minutos com conexão fechada,
repetindo a cada 30 minutos. O quadro fica marcado **ECONOMIA · PAUSADA**, com a
próxima abertura; ele não conta como ao vivo. Não há captura nem detecção durante
a pausa. Em rede normal, isso reduz o tempo de vídeo em cerca de 83%, mas não
limita o volume exato em MB nem elimina o tráfego de negociação.

O erro de 8 segundos sem quadros causa reconexão automática dentro da janela
ativa. Ao chegar a pausa, o painel cancela também as tentativas pendentes. **Parar**
ou **Parar todas** cancela o agendamento apenas das câmeras sem detecção. Desativar Economia volta à transmissão
contínua. Para câmeras com Detectar pessoas, o agendamento roda no servidor, mesmo com
a página fechada. Sem detecção, continua dependendo da página aberta. As câmeras escolhidas para
economia e o mosaico 8/12 são salvos por conta e restaurados ao entrar novamente.
Reabrir o painel não reinicia o ciclo das câmeras monitoradas pelo servidor.
Parar encerra a visualização; desativar Detectar pessoas encerra o monitoramento. O computador não pode suspender.

## Chromecast, Fire TV e alertas

Para Chromecast/Google TV com Google Cast, coloque computador e receptor na mesma
rede Wi-Fi e use o menu do Chrome **Transmitir** (pode ficar em Salvar e compartilhar)
para espelhar a aba do painel. O computador continua executando o sistema. O
endereço localhost pertence ao computador: abri-lo diretamente no receptor não
acessa o painel. Não é necessário expor portas das câmeras.

Fire TV não oferece Google Cast em todos os modelos. Pode precisar de um aplicativo
receptor compatível com Cast, como AirScreen, cuja compatibilidade/custos dependem
do aparelho. Não foi testado em hardware nesta versão. HDMI continua sendo a opção
mais direta; nenhum botão no painel configura Chromecast/Fire TV automaticamente.

Conforme a preferência escolhida, esta versão usa **somente Reports**. E-mail
poderá ser integrado via SMTP com senha de aplicativo; WhatsApp exige serviço como
a WhatsApp Business Platform e configuração/autorização na Meta. Nenhuma mensagem
externa é enviada e nenhuma credencial desses serviços foi solicitada.

## Acesso externo e preferências persistentes

Veja [o guia de acesso externo](docs/remote-access.md) para instalar cloudflared e
iniciar `python3 remote_access.py --port 8097`. O comando pede a senha do sistema
na primeira execução e gera a URL HTTPS no próprio Chromebook. Código pronto não
significa que o túnel já está ativo no computador do usuário: é necessário executar
o comando lá. A senha é armazenada somente como hash local e não é publicada.

A entrada protege painel, APIs e fotos; origens/Host são validados e cookies
externos usam Secure/HttpOnly/SameSite=Strict. APIs de câmera mantêm a autenticação
Yoosee e CSRF. Limite de tentativas protege a senha de entrada. O aplicativo
continua restrito a loopback; a conexão externa chega pelo túnel HTTPS.

As preferências de Economia de dados e o mosaico 8/12 são salvos no banco local
por conta e recuperados em outros acessos após login. A opção de 12 amplia a
capacidade do servidor; uso real simultâneo depende do computador e da conexão.

## Inicialização automática

Com o túnel permanente já funcionando, pare os processos manuais e execute
`python3 configure_startup.py --install` como seu usuário habitual. O instalador
prepara e instala dois serviços systemd, que iniciam com o Linux e reiniciam em
caso de falha. Pode fechar os terminais após conferir duas linhas active em
`systemctl is-active dcs-control.service dcs-tunnel.service`.

[Instruções completas e remoção](docs/remote-access.md#iniciar-servidor-e-túnel-automaticamente-no-linux).
No Chromebook pode ser necessário abrir o Terminal uma vez para iniciar o Linux.
A senha da Yoosee não é armazenada: é preciso abrir o painel e fazer login uma vez após reiniciar o servidor,
mas depois a página pode ser fechada. As preferências das câmeras permanecem
salvas. Atualizações de código exigem reiniciar os serviços.

## Monitoramento com navegador fechado

Faça login uma vez após iniciar o servidor e deixe **Detectar pessoas** ativado
nas câmeras desejadas. O servidor mantém a autorização em memória e inicia o
monitoramento automaticamente, mesmo que nenhuma visualização esteja aberta.

- Detectar pessoas ligado, Economia desligada: monitoramento contínuo.
- Detectar pessoas e Economia ligados: até 5 minutos de conexão/análise em cada
  ciclo de 30 minutos, seguidos de 25 minutos desconectada, sem fotos ou vídeos.
- Detectar pessoas desligado: não há monitoramento em segundo plano.

Pode fechar a aba ou o navegador. Não é preciso deixar o site aberto no
Chromebook, nem manter o túnel disponível para a análise local continuar. Linux,
serviço DCS, acesso à internet das câmeras e computador precisam permanecer ativos,
sem suspensão. Os serviços instalados permitem fechar também os terminais.
**Sair da conta** é o botão do próprio painel e encerra o monitoramento daquela
conta; não é o ato de fechar o Chrome.

O painel e o monitor compartilham a mesma conexão por câmera, dentro do limite
global de 12. Abrir o site não cria outra conexão nem reinicia a economia. Alterar
qualidade pode reiniciar a conexão, sem prolongar a janela de 5 minutos. A fase
do ciclo é mantida em memória pelo servidor; após reiniciar e fazer novo login,
um novo ciclo começa. Não há armazenamento da senha nem do token Yoosee em disco.
Os clipes continuam limitados a dois minutos e terminam parcialmente se a janela
fechar. A retenção de fotos/vídeos continua em 30/15 dias.


## Alertas gratuitos pelo Telegram

Em **Reports → Alertas no Telegram**, configure por conta:

1. No celular, abra o Telegram e converse com **@BotFather**. Use `/newbot`, escolha nome e usuário do bot e copie o token.
2. Abra seu novo bot e toque em **Iniciar**. Consulte seu ID numérico pessoal no **@userinfobot**.
3. Informe token e ID no painel, marque **Ativar alertas com foto** e salve. Clique em **Enviar teste**. Após alguns segundos, confira o celular e **Atualizar status**.

Não envie seu token ao desenvolvedor nem publique capturas com o token. Ele é
armazenado apenas no banco privado `.local/reports/events.sqlite3`, separado por
conta, e nunca devolvido pela API. Deixar o campo vazio mantém o token salvo.
Desmarque a ativação e salve para interromper envios. A configuração sobrevive a
reinicializações; a autorização das câmeras Yoosee ainda exige login após reiniciar.

Cada nova foto de pessoa salva no Reports entra numa fila limitada de envio.
A mensagem contém foto, câmera, horário do servidor e confiança. Quando o servidor
tem `--public-origin`, inclui link autenticado para **Reports → Vídeos**. É um
link para a lista de gravações, não um vídeo público. A gravação pode levar até
dois minutos para finalizar. O celular pode precisar entrar no sistema e na conta
Yoosee para acessar a lista. Sem endereço público configurado, o alerta orienta a
consultar o painel, sem fornecer um link local inacessível.

O envio não abre conexão adicional com a câmera e respeita Detectar pessoas e a
janela de economia. Fotos seguem o agrupamento por presença do Reports (30 segundos contínuos; nova aparição após pelo menos 5 segundos).
O Telegram recebe uma cópia da foto; a retenção de 30/15 dias do Reports não apaga
mensagens do Telegram. O serviço do bot é gratuito, mas usa internet do servidor e
do celular. Ative notificações para a conversa no aplicativo.

Falhas são exibidas em Atualizar status, sem expor token. Não há reenvio automático:
fila cheia, servidor reiniciado ou indisponibilidade podem impedir alertas, enquanto
os registros locais permanecem independentes. Itens da fila expiram em cinco minutos.


## Atualização de qualidade e rostos — 22/10/2026

Execute no Linux do Chromebook, na pasta do projeto, antes de reiniciar os serviços:

```sh
git pull origin main
python3 configure_video.py ~/Yoosee-1.0.0.8.exe --update
python3 configure_faces.py
sudo systemctl restart dcs-control.service dcs-tunnel.service
```

O primeiro comando de preparação recompila o adaptador de vídeo com alvo de 10
quadros/s (anteriormente 5). O segundo baixa os modelos públicos YuNet e SFace do
OpenCV e confere SHA-256 fixado antes de instalá-los em `.local/faces`. Nenhuma foto
é enviada para preparar modelos. Requer OpenCV 4.8 ou superior com YuNet/SFace;
no Debian 13, `sudo apt install python3-opencv` fornece essas APIs. Se o adaptador
não for atualizado, o diagnóstico pede recompilação e não executa binário incompatível.

O painel mostra a resolução **recebida após conversão**, FPS medido e a idade da
última análise de pessoas. Isso não mede a resolução do sensor nem o atraso desde
a captura física. O alvo é até 10 fps; câmera, 4G, navegador e CPU podem entregar
menos. A maior qualidade não cria detalhes ausentes no fluxo enviado pela câmera.

Câmeras monitoradas sem Economia começam em HD com prévia de até 960px, melhorando
a fonte das fotos e gravações. Em Economia, mantêm definição SD e prévia de 640px.
Ampliar uma câmera solicita FHD sem redução da prévia, com retorno ao perfil anterior
ao sair. Em Economia, ampliar mantém a definição escolhida, sem elevar o perfil
automaticamente. Abrir uma qualidade diferente requer reconectar e pode finalizar
um clipe em andamento como parcial. Após falhas repetidas sem quadros, o monitor
reduz a definição para recuperar disponibilidade. FPS pode variar conforme o fluxo;
a gravação amostra a 10fps e pode repetir quadros quando a câmera entrega menos.
MP4 mantém duração de tempo real, sem acelerar movimentos para simular fluidez.

A recuperação começa após 8 segundos sem quadros, com nova tentativa inicial em
2 segundos e recuo progressivo até 60. A negociação P2P ainda pode demorar e usa
fila limitada a duas inicializações simultâneas para preservar o computador. As
pausas de Economia continuam impedindo capturas, análise e reconexões fora da janela.

A detecção de pessoas usa limiar 0,55, análise de quadros novos a cada segundo e
uma segunda escala para cenas largas sem detecção inicial. O ciclo pode demorar
mais em computadores sobrecarregados. Falha de análise em uma câmera não encerra
as demais; o painel informa falhas locais separadamente do status de envio no Telegram.
Movimento rápido, oclusão e baixa resolução ainda podem causar detecções ausentes.

### Aprendizado supervisionado de rostos

No **Reports → Rostos**, ative a captura/comparação e salve. Só câmeras com
**Detectar pessoas** produzem recortes; Economia continua sendo respeitada.
É necessário o rosto estar frontal o suficiente para o detector, ter pelo menos
40px, nitidez e luminosidade adequadas. Sem rosto utilizável, o evento continua
como Pessoa detectada e sem identificação; não é cadastrado um recorte ruim.

Digite um nome numa foto e clique **Salvar nome**. Cada foto nomeada vira um
exemplo SFace normalizado de 128 dimensões, usado imediatamente nas próximas
comparações desta conta. Use o mesmo nome para vários exemplos da mesma pessoa
em iluminação e ângulos diferentes. Há três estados na galeria: exemplo nomeado,
possível conhecido e não reconhecido. Sugestões automáticas não se tornam exemplos
sem sua confirmação. Não há retreinamento dos pesos do modelo nem identificação
infalível. A comparação usa cosseno mínimo 0,55 e margem mínima 0,08 entre nomes;
valores de semelhança não são probabilidades de identidade. Não reconhecido não
significa necessariamente desconhecido, e o recurso não é controle de acesso.

Corrija um nome para corrigir o cadastro. Salvar o campo vazio remove aquele
exemplo do aprendizado. **Excluir foto** remove recorte e descritor. **Apagar todos
os rostos e nomes** elimina a base desta conta e desativa novas capturas. Ao
remover um exemplo, ele deixa de participar das comparações seguintes. Contas
não compartilham nomes, imagens ou descritores. Os recortes não são enviados ao
Telegram; alertas continuam usando as fotos de pessoas do Reports.

Rostos sem nome expiram em 30 dias, com limite de 500 por conta. Exemplos nomeados
ficam até exclusão manual, com limite de 1.000 por conta. Recortes semelhantes da
mesma câmera em 30 segundos são agrupados. Fotos, nomes e descritores faciais são
dados biométricos privados, armazenados no mesmo SQLite protegido dos Reports;
limite o acesso e o cadastro às pessoas e finalidades autorizadas. Pesos dos modelos
e imagens não entram no Git. Fontes: [YuNet](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet)
e [SFace](https://github.com/opencv/opencv_zoo/tree/main/models/face_recognition_sface),
com licenças indicadas pelos respectivos projetos.


## Gravação do cartão, pré-evento e diagnóstico — 28/10/2026

Esta atualização exige recompilar o adaptador (`python3 configure_video.py
~/Yoosee-1.0.0.8.exe --update`) e reiniciar o serviço. A biblioteca original do
instalador continua privada; o Git contém apenas o código do adaptador.

Cada câmera habilitada para detecção mantém até cinco segundos de JPEGs recentes
em memória (limite de 12 MiB por câmera). Ao detectar, a gravação local inclui o
histórico disponível e até 120 segundos seguintes. Não é possível recuperar os
cinco segundos completos se a câmera acabou de abrir, não entregou quadros ou o
limite de memória reduziu o buffer. A pausa de Economia continua fechando a fonte
e finalizando clipes parciais. Não há gravação ou coleta contínua fora da janela.

Após finalizar um clipe local não interrompido, o servidor tenta buscar a mesma
janela no cartão pelo SDK, **experimentalmente**, com apenas uma busca por vez.
A tentativa requer uma das 12 conexões livre, autorização ainda ativa e tempo
suficiente na janela de Economia para terminar; caso contrário mantém o vídeo
local. Falhas têm espera de dez minutos por câmera para reduzir tráfego. O SDK
precisa disponibilizar o intervalo, não bastando haver um cartão inserido.
Confira se a gravação está ativa e se o relógio da câmera está correto no Yoosee.

O caminho usa `setPlaybackDataResource`, `startRecord`, `stopRecord` e
`setTimeListener` do DLL inspecionado. Os horários são Unix em milissegundos,
conforme as chamadas do cliente Windows analisado. Nenhum comando de exclusão ou
formatação do cartão é usado. O processo fica isolado, com limites de tempo,
espaço e tamanho de arquivo; credenciais passam exclusivamente pela entrada padrão.

O original só substitui o local após confirmar timestamps no intervalo solicitado,
duração e decodificação inicial do vídeo. Se o SDK não confirmar o horário, o
local permanece. Em H.264 o servidor remultiplexa sem reduzir FPS nem recodificar;
outros codecs são convertidos para H.264 preservando a cadência recebida, sem
forçar 10fps. O original do cartão nunca é apagado. O Reports identifica a origem,
pré-evento confirmado e situação da busca. Buscar o cartão pode levar alguns
minutos e usa dados adicionais durante a janela permitida. Até ser validado,
o vídeo local fica disponível normalmente.

O caminho do cartão foi compilado e testado com fixtures, incluindo preservação
de 25fps num original H.264 sintético. **A consulta real ao cartão não foi validada
neste ambiente sem acesso às suas câmeras**, e firmwares podem exigir adaptação.
Não é promessa de compatibilidade com todos os modelos. Consulte o status do
clipe no Reports para distinguir busca em andamento, falta de gravação, falta
de conexão livre ou horário não confirmado.

Vídeos do servidor passam a expirar após **15 dias**; fotos continuam em 30 dias.
Arquivos já removidos pela regra antiga não são recuperados. O limite de disco
livre continua impedindo novas gravações quando necessário; quinze dias podem
exigir mais armazenamento. A duração máxima local passa a até 125 segundos com
pré-evento; falhas e Economia podem gerar trechos menores.

Em **Reports → Rostos**, os diagnósticos mostram a última tentativa por câmera,
modelos ausentes, detecção desativada, imagem pequena, falta de nitidez ou luz.
O detector agora verifica rostos mesmo se o detector de corpos não encontrar a
pessoa no mesmo quadro, a cada dois segundos conforme a capacidade do servidor.
O recorte inclui margem ao redor da caixa da pessoa; o mínimo passa de 64 para
40px, com filtro de nitidez revisado. Os critérios de comparação de identidades
continuam conservadores e apenas nomes confirmados treinam os exemplos. Fotos de
pessoas de costas ou com rosto virado para baixo ainda podem não gerar cadastro.

A visualização, as fotos e vídeos usam `object-fit: contain`, sem zoom, corte ou
esticamento. Uma imagem 4:3 ou vertical pode deixar faixas. Não há filtro de crop
na conversão. Isso não recupera áreas ausentes do fluxo fornecido pela câmera.
Se SD mostra um campo diferente do app, compare os perfis SD original, HD e FHD;
use imagens da mesma câmera e posição para confirmar se o SDK fornece outro fluxo.
O tamanho da data sozinho não comprova um corte feito pelo painel.
