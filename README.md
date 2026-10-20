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

A transmissão para quando você clica em Parar, sai da conta, entra novamente,
refaz a consulta de câmeras, encerra o servidor ou deixa de consultar quadros por
20 segundos. Fechar a página também tenta encerrar todas; a expiração por
inatividade cobre a ausência dessa solicitação. A sessão local expira após 20 minutos sem uso. Enquanto o painel está aberto,
uma consulta a cada cinco minutos renova o cookie e a sessão local; consultas de
quadros também renovam a sessão e o prazo dos fluxos ativos. Sem primeiro quadro em 45 segundos ou sem novos quadros
por 15 segundos, a transmissão termina e informa erro. Mudanças de resolução
encerram o fluxo e permitem uma nova tentativa automática. A captura pontual tem seu próprio limite
de 45 segundos mais conversão.

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

Mantenha o servidor e a página abertos no computador ligado à TV por HDMI.
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
as câmeras habilitadas produzem fotos e vídeos. A análise usa o último quadro recente, no máximo a cada 5 segundos por câmera.
Uma foto por câmera é registrada no máximo a cada 60 segundos para reduzir
repetições. Esse intervalo não identifica se uma pessoa é diferente da anterior;
pessoas que passam rapidamente podem não aparecer entre as amostras. Apenas a
classe pessoa é utilizada. Não há detecção de veículos, leitura de placas nem
identificação facial. Registros antigos de veículos e de abertura de câmeras ficam ocultos em Reports,
sem apagar o banco existente. O modelo instalado anteriormente pode ser reutilizado.

Fotos, horário, câmera, caixas e confiança ficam em `.local/reports/events.sqlite3`,
com acesso pelo painel autenticado e separação por conta. A senha/token não são
salvos. Retenção de fotos: até 1.000 registros por conta e 30 dias. Uma rotina
de manutenção remove os expirados enquanto o servidor está ligado. O arquivo de banco pode ocupar espaço mesmo após expirar registros;
SQLite reutiliza essas páginas. Faça backup desse diretório se desejar preservar
os registros. Parar/pausar a câmera também para a produção de novos eventos dela.

Em **Reports**, as abas **Fotos** e **Vídeos** separam os registros. Uma detecção
inicia um MP4 H.264 de até 120 segundos, sem áudio, a 2 quadros/s, reutilizando os
JPEGs da conexão existente. Não abre outra conexão P2P. Cada câmera pode ter um
clipe em andamento; enquanto grava, novas detecções não criam vídeos sobrepostos.
Depois de concluir, outra detecção pode iniciar outro vídeo. Falhas têm intervalo
mínimo de 60 segundos antes de nova tentativa de gravação.

Os vídeos ficam em `.local/reports/videos`, com metadados privados no banco.
São excluídos após 5 dias por manutenção periódica (a cada minuto com servidor
ligado) e ao acessar o armazenamento. Após desligamento, a limpeza ocorre na
próxima inicialização. Parar, perder conexão, desativar detecção ou entrar na pausa
de economia encerra o clipe no trecho disponível, identificado **trecho parcial**.
O sistema não prolonga a janela 4G para completar dois minutos. Ao reiniciar o
servidor, gravações interrompidas ficam como falha, sem disponibilizar MP4 incompleto.

Para limitar consumo local, os encoders usam uma thread, largura máxima de 1280
pixels, e cada arquivo é limitado a aproximadamente 32 MB durante a captura.
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

O erro de 15 segundos sem quadros causa reconexão automática dentro da janela
ativa. Ao chegar a pausa, o painel cancela também as tentativas pendentes. **Parar**
ou **Parar todas** cancela o agendamento. Desativar Economia volta à transmissão
contínua. O agendamento roda enquanto a página estiver aberta. As câmeras escolhidas para
economia e o mosaico 8/12 são salvos por conta e restaurados ao entrar novamente.
O novo acesso começa um novo ciclo. Parar cancela o ciclo atual, mas mantém a preferência. O computador não pode suspender.

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
A senha da Yoosee não é armazenada: o login e a abertura do painel continuam
necessários após reiniciar o servidor. As preferências das câmeras permanecem
salvas. Atualizações de código exigem reiniciar os serviços.
