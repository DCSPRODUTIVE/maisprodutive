# Torre de Controle DCS

Central de monitoramento no navegador para câmeras próprias Yoosee de diferentes
locais, sem VPN. O repositório continua em `DCSPRODUTIVE/maisprodutive`.

## Estado real

- **Confirmado pelo usuário no Chromebook:** login, consulta de oito câmeras e
  captura de imagens reais na maioria delas.
- **Nesta versão:** layout responsivo, mosaico de até oito transmissões
  independentes, busca por nome, tela cheia, modo foco, captura e parada individual
  ou de todas as câmeras. Transmissão experimental de até cinco imagens/s por
  câmera, sem áudio, com conexão P2P mantida aberta.
- **Formato 5:** acrescentada conversão do caminho NV12 de dois planos para YUV420
  planar. A câmera do usuário informou formato 5 em 640×360; a conversão foi
  validada com pixels sintéticos, mas ainda precisa ser confirmada nessa câmera.
- **Ainda não validado com câmeras reais:** transmissão contínua e mosaico
  simultâneo. Não confundir testes locais/sintéticos com essa confirmação.
- **Próxima etapa:** detecção de pessoas e carros, depois alertas. Hospedagem
  pública, áudio, PTZ e gravação não estão implementados.

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
python3 server.py --port 8089
```

Abra `http://localhost:8089` no Chrome do próprio Chromebook. Conecte sua conta,
consulte as câmeras e use **Assistir** para testar uma câmera ou **Assistir todas**
para abrir o mosaico. Esse último ativa o **Modo foco**, que prioriza os vídeos;
**Visão completa** devolve o cabeçalho e a área da conta. Use **Parar**, **Parar
todas**, **Capturar**, busca pelo nome e o botão de tela cheia em cada imagem.

Os estados **Conectando**, **Ao vivo**, **Aguardando** e **Atenção** são calculados
pelos dados recebidos. Uma imagem antiga deixa de contar como ao vivo após três
segundos sem atualização. Falha em uma câmera não encerra as outras. Não há
reconexão automática nem repetição do login. Compartilhe somente a mensagem de
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
Brasil). O botão deve indicar **Testar login Windows**. Se aparecer o modo antigo,
confira a importação do perfil e reinicie o processo do servidor.

## Operação e limites

Há até oito conexões nativas simultâneas no servidor, cada uma com um processo do
SDK Wine e um conversor FFmpeg. No máximo duas câmeras iniciam a conexão ao mesmo
tempo; as demais aparecem como **Na fila** até que uma abertura termine ou receba
o primeiro quadro. Depois de conectadas, as oito podem continuar transmitindo.
A espera na fila não consome os 45 segundos de tentativa do primeiro quadro.
Todos os pools de threads do FFmpeg são limitados. A prévia do mosaico tem até
640 pixels de largura; a abertura individual mantém até 960 pixels. Isso altera
somente a conversão local, sem modificar a qualidade enviada pela câmera. O mosaico começa pelas primeiras oito câmeras da
conta. Consumo de CPU, memória e internet cresce com as câmeras abertas. Não há
alteração automática de qualidade ou configuração das câmeras.

A conexão é reutilizada para os quadros seguintes; não se abre um login a cada
imagem. O painel recebe somente o JPEG mais recente de cada câmera, sem acumular
um histórico. **Capturar** reaproveita um quadro da transmissão quando ela já está
aberta. Uma captura sem transmissão abre um processo pontual.

A transmissão para quando você clica em Parar, sai da conta, entra novamente,
refaz a consulta de câmeras, encerra o servidor ou deixa de consultar quadros por
20 segundos. Fechar a página também tenta encerrar todas; a expiração por
inatividade cobre a ausência dessa solicitação. A sessão dura no máximo 20 minutos,
sem renovação automática. Sem primeiro quadro em 45 segundos ou sem novos quadros
por 15 segundos, a transmissão termina e informa erro. Mudanças de resolução
encerram o fluxo para reinício explícito. A captura pontual tem seu próprio limite
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

69 testes Python e 14 de interface passaram. Também foram exercitados o binário
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
