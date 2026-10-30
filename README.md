# Torre de Controle DCS

Central de monitoramento no navegador para câmeras próprias Yoosee de diferentes
locais, sem VPN. O repositório continua em `DCSPRODUTIVE/maisprodutive`.

## Estado real

- **Confirmado pelo usuário no Chromebook:** login, consulta de oito câmeras e
  captura de imagens reais na maioria delas.
- **Nesta versão:** layout responsivo, mosaico com seleção de 8 ou 12 transmissões
  independentes, busca por nome, tela cheia, modo foco, captura e parada individual
  ou de todas as câmeras. Transmissão experimental de até dez imagens/s por
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
  Requer instalar o modelo e OpenCV conforme abaixo. Telegram é opcional e exige configuração.
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


## Atualização de estabilidade, cartões e webcam — 30/10/2026

No Linux do servidor, atualize e recompile o adaptador antes de reiniciar:

```sh
cd ~/maisprodutive
git pull origin main
python3 configure_video.py ~/Yoosee-1.0.0.8.exe --update
sudo systemctl restart dcs-control.service dcs-tunnel.service
```

Abra o painel, atualize com Ctrl+Shift+R e entre na conta novamente. Nenhuma alteração
no DNS ou no túnel é necessária. A atualização não pode ser aplicada ao Chromebook
por este ambiente sem acesso administrativo remoto a ele.

### Transmissão e recuperação

O navegador recebe JPEGs por uma conexão MJPEG contínua, sem esperar uma requisição
JSON para cada quadro. Os diagnósticos usam consultas leves separadas. Várias abas
compartilham a fonte da câmera; fechar o painel mantém o monitoramento habilitado.
Há até 12 fontes e 16 visualizações contínuas. A conexão do navegador pode ser
reaberta sem reiniciar a conexão P2P da câmera.

O monitor verifica fontes sem quadros independentemente do navegador. Após oito
segundos sem quadros, encerra a fonte parada e tenta reabrir com espera progressiva
entre dois e 60 segundos. A primeira imagem tem prazo de 30 segundos depois de
iniciar a conexão; a negociação usa uma fila limitada. Imagens antigas permanecem
visíveis como último quadro, sem serem consideradas transmissão ao vivo.

O padrão de abertura é SD/640px para reduzir carga e tráfego. Selecione HD/FHD na
câmera desejada quando houver capacidade. Ampliar a câmera preserva a qualidade
selecionada e a conexão. O painel mostra resolução recebida, FPS medido e idade da
análise. Esses valores não medem a resolução do sensor ou o atraso físico.
O alvo de captura é até 10 FPS; rede, firmware e computador podem entregar menos.
A apresentação usa `object-fit: contain`, sem corte ou esticamento. Se o SDK fornece
um campo menor que o app, mudar o CSS não recupera a área ausente; compare os
perfis de qualidade da própria câmera.

### Gravações e pessoas

O reconhecimento/cadastro de rostos foi removido. A detecção de pessoas continua
por câmera, com análise de quadros recentes e registros no Reports. As bases antigas
de rostos não são carregadas nem expostas por rotas do sistema; arquivos privados
legados não são apagados automaticamente por esta atualização.

A captura local e a codificação agora são etapas separadas. O servidor guarda os
JPEGs recebidos e seus horários e depois produz o MP4 com cadência variável. Não
repete imagens para anunciar 10 FPS. O vídeo preserva pausas reais da fonte; não é
possível reconstruir movimento que a câmera não entregou. O Reports mostra FPS de
quadros distintos e maior intervalo entre eles. A codificação usa no máximo dois
processos simultâneos, arquivos temporários limitados e reserva de disco livre.

O clipe inclui até cinco segundos anteriores disponíveis e até 120 segundos após a
detecção. Histórico é limitado a 12 MiB por câmera; quedas, início recente ou Economia
podem reduzir o pré-evento ou interromper o clipe. Vídeos expiram em **15 dias**;
fotos em **30 dias**. A retenção não recupera arquivos excluídos anteriormente.

### Cartões de memória e backup

Em **Reports → Cartões de memória e backup**, escolha uma câmera e um intervalo
passado de até uma hora para consultar as gravações. Selecione um resultado ou um
intervalo de até dois minutos e clique em fazer backup. O trabalho continua no
servidor se a página fechar. O MP4 pronto aparece em Vídeos e pode ser baixado por
**Baixar MP4**. Os backups seguem a retenção de 15 dias; baixe uma cópia para guardar
por mais tempo. A operação não apaga nem formata o cartão. Não é backup integral
ou contínuo do cartão.

Depois de um clipe de detecção completo, o servidor também tenta obter a mesma
janela no cartão. Consulta primeiro os arquivos, abre o arquivo que cobre o início
e solicita posicionamento no horário desejado. Só substitui o vídeo local após
confirmar horário, duração e decodificação. Falhas preservam o vídeo local e geram
um diagnóstico específico; tentativas automáticas malsucedidas têm espera de dez
minutos por câmera. Em H.264, a cópia é remultiplexada sem reduzir FPS; outros codecs
podem precisar de conversão.

**A compatibilidade do cartão é experimental e precisa ser validada nas câmeras
reais.** A interface nativa foi analisada e compilada, mas este ambiente não tem
acesso ao hardware. Listagem indisponível não significa que o cartão está vazio.
O cartão precisa gravar no app e o relógio da câmera deve estar correto.
Consultas e downloads usam dados adicionais, uma conexão livre e uma única fila.
Câmeras em Economia só permitem esse trabalho dentro da janela ativa e se houver
tempo para concluir; nenhuma busca deve contornar a pausa.

### Webcam do servidor

Uma webcam integrada ou USB exposta ao Linux como `/dev/videoN` aparece no painel
como **Webcam do servidor**. Começa desligada. Clique em **Ativar webcam** para
permitir captura e **Desativar webcam** para fechar o dispositivo, inclusive o
monitoramento em segundo plano. Essa preferência é salva por conta. O painel
não solicita a câmera do celular ou computador usado para visitar o site.

Depois de ativada, pode usar **Detectar pessoas** e **Economia de dados**, com as
mesmas regras de foto, vídeo, Telegram configurado e retenção. Economia abre por
cinco minutos a cada 30 minutos e mantém o último quadro durante a pausa; fora da
janela não há detecção. A webcam usa captura de 640×480 a até 10 FPS e não possui
cartão consultável pelo sistema. A detecção permanece opcional.

No Chromebook, a câmera integrada pode não estar disponível ao Linux. O ChromeOS
precisa permitir compartilhar uma webcam USB compatível com o Linux, e o usuário
do serviço precisa ter acesso de leitura e escrita ao dispositivo. Quando houver
um grupo `video` controlando o dispositivo, ajuste a participação do usuário nesse
grupo e reinicie a sessão/serviço. Se `/dev/video*` não existir no Linux, o servidor
não consegue capturar essa câmera; o painel informa a indisponibilidade.
A câmera também pode falhar se já estiver ocupada por outro aplicativo.


### Correção dos horários do cartão — 30/10/2026

Atualize o código e recompile o adaptador com `configure_video.py --update` conforme
os comandos acima. O relógio da reprodução do SDK usa microssegundos; a lista e a
interface usam milissegundos Unix. A revisão normaliza essas unidades e posiciona
a reprodução no início escolhido, sem usar o fim como posição de apresentação.
Nenhuma compensação arbitrária de fuso horário é aplicada.

A seleção de um resultado do cartão preserva segundos e milissegundos. Um trecho
que cruza arquivos de aproximadamente um minuto é dividido nos limites listados,
exportado por partes e juntado sem reduzir FPS. Esse caminho é compartilhado pelo
backup manual e pela busca após detecções, incluindo a janela de pré-evento.
São aceitas até oito partes por trecho; lacunas ou mudança incompatível do formato
impedem a substituição, preservando o vídeo local da detecção. Não há montagem de
imagens para simular o movimento ausente. O trabalho tem tempo e espaço limitados
e continua respeitando Economia; pode ser necessário aguardar o cartão finalizar
um arquivo recente antes de ele aparecer na lista.

A listagem foi confirmada pelo usuário. Posicionamento e cópia da nova revisão
precisam ser repetidos nas câmeras reais; testes de horários e concatenação não
substituem a validação do firmware. Consulte um período confirmado no app e use
Selecionar trecho para manter os limites exatos do arquivo retornado.


### Revisão de reprodução e diagnóstico do cartão — 30/10/2026

A abertura inicial agora passa o instante desejado nos dois campos de posição,
como o cliente Windows; o fim do arquivo não é posição de apresentação. Só há
uma nova tentativa de seek se a primeira abertura não confirmar o relógio pedido.
O backup reaproveita a lista já obtida e valida os limites de cada arquivo antes
de abrir suas partes, evitando consultas repetidas durante a cópia.

A consulta usa uma janela menor ao redor do trecho. Respostas parciais/expiradas
são diferenciadas de estruturas incompatíveis e podem ser repetidas uma vez,
respeitando o prazo e Economia. Uma resposta parcial não comprova ausência de
arquivos. Pequenos intervalos entre arquivos (até 250 ms por limite e um segundo
somado por trecho) deixam de causar uma falsa lacuna; o Reports informa o total
omitido. Não são inventados quadros para preencher esse tempo. Lacunas maiores
continuam impedindo substituição do vídeo local.

Falhas novas mostram diagnóstico numérico da etapa, quadros e retornos de horário,
além do desvio do relógio quando disponível. Não incluem tokens, IDs de sessão,
conteúdo bruto de mensagens do fornecedor ou imagens adicionais. Um backup manual
sem vídeo deixa de afirmar que preservou um vídeo local inexistente. Os vídeos
locais de detecção continuam preservados até a cópia do cartão ser validada.

Execute novamente a atualização/recompilação descrita acima. A cópia real do cartão
continua dependendo da confirmação na câmera; a listagem, já confirmada, não basta
para comprovar suporte à reprodução/gravação nessa versão do SDK.


### Visão completa para TV e último quadro

**Visão completa** passa a mostrar somente imagem, nome e estado de cada câmera.
O mosaico calcula colunas e linhas para aproveitar a tela com 8 ou 12 câmeras,
sem cortar ou esticar a imagem. A câmera ampliada também oculta os controles.
Use **Esc** para sair; o botão de saída aparece ao passar o ponteiro no canto
superior direito. Um clique explícito em Visão completa ou Assistir todas pode
ativar a tela cheia do navegador. A abertura automática respeita as restrições do
navegador e pode precisar de F11 ou desse clique para esconder a barra do Chrome.

O painel mantém a última imagem válida durante Economia, espera, falha e
reconexão. Ao abrir a página durante uma pausa, ele pode recuperar a imagem já
guardada no servidor, sem abrir uma nova conexão com a câmera. O selo Ao vivo
exige quadros recentes; a imagem preservada continua marcada como pausada,
aguardando ou reconectando. Se não houve nenhum quadro válido desde que o servidor
iniciou, não há imagem anterior para mostrar. Logout e término da sessão removem
as imagens da conta do painel. Esses ajustes não elevam a qualidade nem o consumo
de dados da fonte ao entrar em tela cheia.


### Finalização de gravações e trechos parciais do cartão

O adaptador passa a esperar o avanço do relógio de reprodução com limite total
controlado pelo servidor; uma entrega mais lenta não é encerrada apenas pela
duração nominal do trecho mais oito segundos. A espera sem progresso passa a
até 15 segundos, sempre dentro do prazo do trabalho e da janela permitida pela
Economia. O intervalo confirmado é congelado antes de fechar o gravador, pois a
reprodução pode continuar avançando enquanto o arquivo é finalizado.

Se a câmera entregar somente parte do intervalo, mas com horário válido e MP4
compatível com a duração confirmada, a parte pode ser baixada como **parcial**.
Um backup manual não é apresentado como completo. Na busca automática da detecção,
a cópia parcial aparece separadamente como **Trecho parcial do cartão**; o vídeo
local original permanece. O Reports mostra início e fim confirmados da cópia.
Vídeos parciais também expiram em 15 dias. Horários de outro intervalo, arquivos
inválidos e durações incompatíveis continuam sendo rejeitados.

Essa revisão exige atualizar e recompilar novamente o adaptador. O diagnóstico
real do usuário confirmou a chegada de quadros; a conclusão de um backup completo
ainda depende do próximo teste na câmera. A mudança não inventa os segundos que
não forem entregues pelo SDK.
