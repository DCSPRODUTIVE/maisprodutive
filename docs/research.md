# Evidências da investigação — 20/10/2026

## Fontes consultadas

- [GwellDemo, conta indicada pelo demo antigo](https://github.com/jwkj/GwellDemo).
  README com atualizações até 2019; exemplos de login, sessão, consulta e P2P.
- [GwellDemo antigo](https://github.com/dxsdyhm/GwellDemo).
- [GWNet para iOS](https://github.com/GWTimes/GWNet).
- [Página Yoosee no APKPure](https://apkpure.com/yoosee/com.yoosee).
  A página acessível anuncia Gwell, pacote `com.yoosee`, versões 6.45/6.45.1 e
  aponta para `https://download.yoosee.com`. Isso é informação do catálogo,
  não inspeção de um APK ou confirmação da versão instalada no celular.
- [YooFree](https://github.com/Wennington123/YooFree): cliente local; seu README
  não comprova login remoto na nuvem Yoosee.

Nenhum código de terceiros foi executado para autenticar uma conta ou acessar uma
câmera. A decompilação é estática. O decompilador CFR 0.152 foi obtido pelo Maven
Central e seu SHA-256 conferido com o checksum publicado no mesmo repositório.

## Artefatos inspecionados

Obtidos por HTTPS em `raw.githubusercontent.com/jwkj/GwellDemo/master/app/libs/`:

| Arquivo | SHA-256 observado |
| --- | --- |
| libhttp-release.aar | `8277901ab2476aa810e3ff069599414f016db3f746239fd4c5586a68a9259b91` |
| p2p-core-release.aar | `11d6c2032ab52ce8502dcbca66f203929397af2c9920d58c29388713fabf8d5b` |

Esses hashes identificam os arquivos baixados; não equivalem a assinatura do
fabricante. Artefatos e fontes decompiladas permanecem fora do checkout, em
`/workspace/scratch/yoosee-research`, sem redistribuição das bibliotecas no projeto.

## Camada HTTP

Classes inspecionadas: `HttpService`, `HttpMethods`, `HttpSender`, `HttpRegistrant`,
`ServicePath`, `LoginGResult`, `LoginResult`, `LoadDeviceResult`, `DeviceSync`, `MD5`.

- Login: POST `Users/LoginCheck.ashx`, com parâmetros na query, incluindo `User`,
  `Pwd`, `VersionFlag`, `SessionID2` e `AnonymousId`.
- Parâmetros comuns: `AppID`, `AppToken`, `Language`, `AppOS=3`, `AppName`,
  `AppVersion`, `PackageName` e `ApiVersion=1`.
- O hash do SDK antigo é MD5 hexadecimal em maiúsculas. Sua implementação usa
  quantidade de caracteres UTF-16 como comprimento de bytes UTF-8; o cliente
  experimental reproduz esse comportamento para senhas não ASCII.
- IDs de conta numéricos iniciados em zero são convertidos para inteiro de 32
  bits com bit de sinal. A resposta faz a conversão inversa.
- Sessão: `UserID`, `SessionID`, `SessionID2`, `P2PVerifyCode1`, `P2PVerifyCode2`;
  há também uma entidade com nomes equivalentes dentro de `data`.
- Consulta: POST `Relationship/LoadDeviceInfo.ashx`, com `PreDeviceID`,
  `RequestCount`, `MyUpgradeFlag`, `UpgCheckList`, `NotReturnDeleted` e sessão.
- Dispositivos incluem `devId`, `remarkName`, `secretKey` e metadados. Apenas
  identificador e nome são retornados ao painel; segredos não são repassados.

A presença de duas entidades de resposta não comprova que ambas são aceitas hoje.
O cliente rejeita respostas desconhecidas, erros e sessões incompletas. Não troca
automaticamente de servidor após uma falha de login nem tenta adivinhar senhas.

O SDK antigo contém código que aceita certificados/hostnames sem validação. Essa
prática **não foi reproduzida**: o cliente usa a validação TLS padrão do Python.

## Vídeo/P2P

`p2p-core-release.aar` inclui `libmediaplayer.so`, `libp2pav.so`, `libSDL.so`,
`libmp4v2.so`, nas arquiteturas `armeabi` e `arm64-v8a`. A inspeção ELF com
`readelf -d` identifica dependências Android, como `libandroid.so`, `liblog.so`,
`libEGL.so` e `libGLESv2.so`. A classe `MediaPlayer` declara métodos JNI nativos
de conexão, controle e vídeo. Copiar essa biblioteca para Python não implementa
essas funções no Linux x86_64.

O README descreve P2P 3.0 com `localAreaIp=0` para comunicação fora da LAN. Isso
indica suporte remoto no SDK histórico; não prova passagem por CGNAT ou suporte
ao firmware atual. Ainda não foram enviados pacotes P2P ou recebidos quadros.

## Resultados atuais

Testes automatizados usam fixtures sintéticas e chamadas reais somente ao servidor
local. Não representam login ou vídeo real. O diagnóstico de rede separado registra
a disponibilidade dos quatro hosts sem credenciais. Rede liberada, identificação
de aplicativo válida e credenciais de usuário continuam necessárias para o teste
real. Nenhuma detecção de pessoas ou notificação foi implementada.

## Nova verificação após a liberação parcial da rede

`https://api3.cloud-links.net/Users/LoginCheck.ashx` respondeu HTTP 200 a um GET
sem parâmetros, com `error_code=10901020` e mensagem de parâmetros ausentes.
Nenhum nome de usuário, senha, token de aplicativo ou sessão foi enviado.
Isso confirma que o endpoint responde, mas não que o login legado funciona.

A página `https://download.yoosee.com` também está acessível. Foram inspecionados
os recursos públicos `/statics/js/app.32a4fc75.js` e
`/statics/js/chunk-6ba6cdf0.63a44603.js`. A tabela de strings do primeiro foi
resolvida estaticamente, sem executar o JavaScript do site. O segundo revela:

- GET `https://upg.cloudlinks.cn/latestVersions?clientIp=0.0.0.0` para catálogo;
- GET `https://upg.cloudlinks.cn/lastCms?clientIp=0.0.0.0` para cliente de PC;
- URL de Android `https://upg-cdn.yoosee.co/yoosee-{version}-release.apk`, com
  versão obtida do catálogo, sem valor adivinhado.

O proxy retorna erro 403 no túnel HTTPS para `upg.cloudlinks.cn` e
`upg-cdn.yoosee.co`. Esses destinos foram acrescentados ao rascunho de rede para
permitir continuar a obtenção oficial. Não houve download ou verificação de um
APK novo. Credenciais de usuário e credenciais válidas de aplicativo continuam
ausentes. Nenhuma senha foi adivinhada e nenhum mecanismo de autenticação foi
contornado.

## Após a publicação da configuração pelo usuário

O catálogo e o CDN ficaram acessíveis. A resposta oficial de `latestVersions`
anuncia Android `00.46.06.46`. O arquivo correspondente foi baixado por HTTPS:

`https://upg-cdn.yoosee.co/yoosee-00.46.06.46-release.apk`

- Tamanho: **310.347.986 bytes**, correspondente ao Content-Length.
- SHA-256 do arquivo: `43027781f767e9a359e2b3399f49f236d2eb535da7c912b4f9a9cc718b994e27`.
- Manifesto: pacote `com.yoosee`, versão **6.46.2**, código **6462**.
- CRC do contêiner ZIP: sem erro na verificação de todas as entradas.
- `apksigtool 0.1.0`: **v2 verified**, **v3 verified**, saída 0.
- SHA-256 do certificado v2: `7373ba00391ff5ed19212c777c9b36d52ce1ce407c056a302e5c106e6466f50f`.

`apksigtool` se apresenta como ferramenta protótipo; seu resultado verifica a
assinatura interna, sem comparação independente do certificado com a Play Store.
O arquivo veio do CDN indicado pelo código da página oficial, não de um espelho.
Ele permanece fora do checkout, sem instalação ou execução.

A análise com `androguard 4.1.4` identificou dez DEX. Nove contêm apenas classes
dummy `com.example.helloworld`; o principal contém `com.wrapper.proxyapplication`
e `com.yoosee.MyWrapperProxyApplication`. Existem bibliotecas `libshella` e
`libshell-super.com.yoosee.so`. O código normal de login não fica disponível em
uma leitura direta dessas classes. Isso impede comparar o fluxo atual usando
apenas o procedimento de análise estática empregado até aqui.

O APK inclui `libp2pav.so`, `libiotvideomulti.so`, `libgwmediaplayer.so`, somente
em `armeabi`/`arm64-v8a`. A inspeção ELF confirmou dependências Android/Bionic,
como `libandroid.so`, `liblog.so`, `libEGL.so` e `libGLESv2.so`. Os headers em
assets são de multimídia e não constituem documentação de login da conta.

O portal `https://sdk.yoosee.co` continua retornando HTTP 503. O catálogo de PC
retorna um instalador Windows oficial `CMSSetup_1.0.0.54.exe` no host
`cms-1251981983.cos.ap-beijing.myqcloud.com`, mas o proxy bloqueia esse host.
O instalador Windows não foi baixado ou executado. Isso não bloqueia o teste de
conectividade implementado, e não foi adicionado como requisito obrigatório.

**Resultado:** a rede para catálogo/APK foi resolvida. Permanecem sem validação
a identificação de desenvolvedor, a autenticação de uma conta real e o vídeo.
O novo botão do painel apenas testa os endpoints públicos sem credenciais; ele
não transforma esse resultado em sucesso de login ou acesso a câmeras.

## Tentativa explícita apenas com login/senha, solicitada pelo usuário

O modo `account-experimental` foi acrescentado para permitir uma tentativa normal
de autenticação da conta própria sem identificação de aplicativo. Ele omite
`AppID`/`AppToken`, mas conserva o endpoint, os campos de conta e o hash do SDK
histórico. Isso é uma hipótese experimental, não uma compatibilidade inferida do
APK atual ou confirmação de que esses parâmetros são opcionais para a Yoosee.

Não foram extraídas chaves de aplicativo, criados tokens falsos ou modificados
controles de acesso do serviço. A solicitação usa a senha fornecida pelo usuário
localmente e só aceita sucesso explícito acompanhado de sessão no formato esperado.
Uma rejeição não tenta outro host, senha, hash alternativo ou credencial SDK.

O painel agora habilita os campos quando ambos os parâmetros SDK estão ausentes,
mostra que o modo é experimental e expõe o código de rejeição sem a resposta bruta.
Ambos os parâmetros presentes selecionam o modo SDK original; configuração parcial
é rejeitada antes de usar a rede. São 28 testes Python e 5 testes da interface,
com respostas sintéticas para a autenticação. Continua pendente um envio real pelo
usuário no Chromebook e a observação da resposta, sem compartilhar sua senha.

## Cliente Windows 1.0.0.8 enviado em três partes

O usuário enviou `Yoosee-parte-aa`, `-ab` e `-ac`, concatenados nessa ordem.
O instalador reconstruído tem 79.184.684 bytes e SHA-256
`0f0a6901fe4aefdc1d77dc0d3e1182df61711165f677811f394f280ee42e6d21`.
É um instalador NSIS 3 Unicode/LZMA. Foi extraído, sem executar código Windows,
com 7zip Debian 25.01+dfsg-1~deb13u2. O pacote de extração foi validado pela
cadeia InRelease assinada → checksum Packages.xz → checksum do .deb.

O `Yoosee.exe` interno tem 8.977.920 bytes, é PE x64/Qt5 e tem SHA-256
`8720a7c99022cf51fb53b80e91ae151e4e45c8992cbe83b839c57a782c0b323a`.
Os dois arquivos não têm entrada de assinatura Authenticode. A origem informada
foi `https://yooseeapp.org/yoosee-for-pc/`; a identidade do fabricante não foi
estabelecida. O hash fixa o arquivo inspecionado, sem autenticar essa origem.
O download oferecido depois para 1.0.0.14 permaneceu bloqueado pelo proxy e
não foi tratado como equivalente à versão analisada.

### Evidências do protocolo

Análise com pefile e Capstone, seguindo referências RIP a strings e chamadas
Qt. Endereços virtuais correspondem à imagem original, base `0x140000000`:

- `UserMobileLogin`: `0x14017f610..0x14018102a`.
- Construtor WebApiModel: `0x140179310`, chamado em `0x140152710` antes do login.
- Helper HTTP JSON: `0x1401841a0`.
- Composição da mensagem para assinatura: `0x140183090`.
- `giote_user_signature`: `0x140183a40`.

O destino é `https://openapi-iot.cloudlinks.cn`, diferente dos endpoints históricos.
O login é POST JSON em `/openapi/app/user/login/account`, Content-Type
`application/json; charset=utf-8`, sem a assinatura usada posteriormente na lista.
Campos comuns identificados: `language="ZH"`, `pkgName="Yoosee.PC"`,
`appName="Yoosee.PC"`, `terminalOS=1`, `appVersion="10"`, `apiVersion="10"`,
mais `appId`/`appToken`. Estes dois últimos são parâmetros estáticos do cliente;
seus valores não são documentados nem versionados. A importação local lê os RVAs
`0x5BB5A8` e `0x5BB5E0` somente após validar o hash exato do executável.

O corpo de login tem `action="account"`, `uniqueId` derivado do MAC local,
`pwd` MD5 hexadecimal minúsculo e os campos de conta. E-mail usa
`loginMode="email"` e `email`; telefone usa `loginMode="mobile"`, `mobile`
e `mobileArea` (país). O fluxo nativo converte a senha para Latin-1 antes do MD5;
caracteres fora dessa codificação tornam-se `?` por unidade UTF-16. A implementação
reproduz essa conversão. A resposta aceita é `code=0` e `data.accessId` com
`data.accessToken`. Um código positivo ou uma sessão incompleta não é sucesso.

A lista é GET em `/openapi/app/user/device/listDevice`. A query contém parâmetros
comuns, `lastDeviceId="0"` inicialmente e os primeiros 96 caracteres de
`accessToken`. A mensagem assinada inclui também `host="openapi-iot.cloudlinks.cn"`,
`x-iotvideo-accessid`, `x-iotvideo-nonce` e `x-iotvideo-timestamp`. Ordena chaves
lexicograficamente e une pares `chave:valor` com newline, sem newline final.
A assinatura é Base64 de HMAC-SHA1, usando como chave os 16 bytes decodificados
dos últimos 32 caracteres hexadecimais do token completo. A estrutura foi também
comparada com a função de assinatura JavaScript pública do site oficial.
Cabeçalhos: `X-IotVideo-AccessID`, `X-IotVideo-Nonce`, `X-IotVideo-Timestamp`,
`X-IotVideo-Signature`. O nonce nativo é um contador módulo 1000; o cliente Python
usa aleatoriedade no mesmo intervalo. Tokens incompatíveis são rejeitados
localmente; não se inventam sessões nem se tentam assinaturas alternativas.

A paginação lê `data.deviceList` e `data.leftNum`. O painel recebe apenas ID e
nome; chaves e tokens de dispositivos não são encaminhados ao navegador.
A implementação preserva a verificação TLS, apesar de o binário desativá-la.

### Implementação e limites do teste

`configure_desktop.py` importa o perfil ignorado pelo Git, com permissão 0600,
sem executar o instalador. Só aceita os dois hashes conhecidos. Uma configuração
existente diferente é preservada; uma importação idêntica é idempotente.
`desktop.py` implementa o protocolo; `server.py` seleciona o perfil Windows quando
presente e não tenta novamente pelo protocolo antigo se houver rejeição.
O teste de comunicação do painel seleciona o endpoint do protocolo ativo,
sem senha ou tentativa de autenticação.

Importação do instalador real e reimportação idêntica verificadas nesta máquina.
46 testes Python e 6 de interface passaram com respostas sintéticas, incluindo
assinatura determinística, erros sem vazamento de tokens, paginação e seleção do
cliente pelo servidor. Isso não confirma autenticação de uma conta real.
O proxy da nuvem retornou 403 para o novo host; nenhuma credencial de conta foi
usada na investigação. O teste real deve ocorrer no painel local do usuário.

Há também `IotVideoSDK.dll`, x64, com exports de registro e player, mas nenhuma
biblioteca foi executada ou integrada. Transporte P2P, decodificação e entrega de
vídeo ao navegador continuam pendentes. O acesso remoto do aplicativo original
não implica que uma simples listagem HTTP forneça os quadros de vídeo.

## Confirmação real e adaptador experimental de imagem

Em 20/10/2026, o usuário confirmou no Chromebook o login Windows e a consulta de
oito câmeras da sua própria conta, com captura de tela do painel. Isso valida
esse fluxo de autenticação/listagem no ambiente dele. Os identificadores e o
login não são reproduzidos neste documento. Não há ainda confirmação de quadros.

### Caminho nativo identificado

No `Yoosee.exe` analisado:

- `0x140160620`: `IoTVideoSdkModel::UserRegister`; chamada de `getInstance()` e
  registro com `accessId` e `accessToken` da sessão (`Register` em `0x14016097c`).
- `0x140168ef0`: criação do player de 16 bytes, instalação do VideoRender,
  `setDataResource` em `0x14016981f` com ID, tipo de conexão 1, definição e canal;
  `play` em `0x140169870`.
- VideoRenderCase: construtor `0x1401a34b0`, vtable `0x1405c1110`. Entradas:
  destrutor `0x1401a3530`, init `0x1401a3650`, frameUpdate `0x1401a3590`,
  release `0x1401a36a0`. Init lê formato em AVHeader+0x18. O frameUpdate lê
  largura/altura em AVData+0x40/+0x44 e três ponteiros de planos em +0/+0x10/+0x20.
  O renderer original também passa somente esses ponteiros, dimensões e formato
  ao renderizador, sem pitches adicionais.

No `IotVideoSDK.dll`, x64, exports relevantes:

- construtor IoTVideoPlayer `0x18002db70` (objeto externo de 16 bytes);
- Register `0x180030950`: ID decimal em std::string por valor e token por referência;
  a string por valor é destruída pela função. A ponte usa layout MSVC x64 e
  alocação da UCRT para compatibilidade do buffer destruído;
- setDataResource `0x18002e510`, play `0x18002e140`, setVideoRender exportado.

`native/yoosee_snapshot.c` implementa uma ponte C própria, sem código do fabricante.
Reconstrói a interface virtual de renderização e espera um quadro YUV420 planar.
Só emite o quadro por um handle privado; stdout/stderr do SDK são suprimidos.
Tokens entram por stdin, nunca argumentos ou arquivos de configuração.
`video.py` limita o processo a 45 segundos, valida o formato e tamanho e converte
um quadro em JPEG com FFmpeg. Não há login automático adicional nem fallback.
`DesktopClient.snapshot` só aceita IDs da última consulta bem-sucedida da conta;
consulta falha ou novo login apagam essa autorização. O endpoint mantém as mesmas
verificações de sessão, Origin e CSRF e limita o servidor a uma captura por vez.

`configure_video.py` valida o instalador já conhecido, extrai quatro DLLs e
compila a ponte com MinGW. Dados e binários ficam ignorados em `.local/video`.
A preparação não executa o SDK. Hashes das DLLs reconhecidas:

| Arquivo | SHA-256 |
| --- | --- |
| IotVideoSDK.dll | e1a93b18fbac566f5350a5e9b6156839acca48fa0088689993301dec77be6053 |
| msvcp140.dll | 10ddff48d704c6007e4c2d53fb4856b5e5e79479503366236246a323aaa76e9d |
| vcruntime140.dll | 8ee6b49830436ff3bec9ba89213395427b5535813930489f118721fd3d2d942c |
| vcruntime140_1.dll | f8bc270449ca6bb6345e88be3632d465c0a7595197c7954357dc5066ed50ae44 |

### O que foi executado e o que permanece pendente

Diferentemente da análise inicial, nesta etapa a DLL foi **carregada e executada**
pelo adaptador em Wine 10, dentro de contêiner Debian trixie com `--network none`.
Não houve credenciais, câmera ou registro externo. O teste `--sdk-selftest`
construiu o player e instalou o renderer, retornando 0. O teste
`--frame-selftest` forneceu um quadro YUV sintético de 16x16 à mesma função de
renderização; o resultado foi convertido em JPEG real pelo FFmpeg. Esses testes
não exercitam registro da sessão, NAT traversal, recepção ou decodificação de
vídeo de uma câmera real e não demonstram compatibilidade completa da ABI.

A preparação real a partir do instalador, a compilação com warnings como erros e
a reexecução idempotente passaram. São 53 testes Python e 8 testes da interface,
incluindo autorização por câmera, exclusão mútua, expiração do processo, ausência
de tokens em argumentos/respostas e identificação da imagem como captura pontual.
Falta o teste do usuário no Chromebook com uma câmera real. O primeiro quadro,
se recebido, permitirá avaliar o próximo passo de transmissão contínua. Áudio,
PTZ, gravação, detecção de pessoas e alertas não foram implementados.

## Correção após rejeição do primeiro quadro

O usuário executou o adaptador no Chromebook e recebeu o erro antigo de formato.
Naquela versão, o mesmo código 16 agrupava formato, dimensões, planos ausentes e
falha de escrita; a mensagem não permite afirmar qual desses casos ocorreu, nem
que um quadro decodificável tenha sido recebido.

A revisão de `0x1401ae090` no executável original identificou a tabela de dispatch
em `0x1401ae1b4`: tanto o código 0 quanto 1 seguem o ramo `0x1401ae105`, que
encaminha três planos, largura e meias larguras ao renderizador. A ponte anterior
aceitava somente 0. O novo adaptador aceita ambos pelo mesmo caminho de planos,
conforme o renderer original, sem tentar adivinhar outros formatos.

A rotina H264 `0x1800209a0..0x180020d12` confirma que os planos fornecidos pelo SDK
são compactados a partir do AVFrame, removendo pitches de origem quando necessário.
Escreve os tamanhos dos planos em AVData+8/+0x18/+0x28 e dimensões em +0x40/+0x44.
A ponte agora valida esses tamanhos antes de ler os planos. Dados iniciais
incompletos são ignorados dentro do mesmo limite de 25 segundos, sem novo login,
registro ou conexão de câmera. O primeiro erro não encerra mais a captura.

Erros distintos: 17 formato, 18 dimensões, 19 planos ausentes, 20 tamanho de buffer,
21 transferência. Se nenhum quadro válido chegar após callbacks rejeitados, a
ponte emite somente `MPVD1 motivo formato largura altura`. O servidor aceita
apenas esse esquema numérico completo, com motivo igual ao exit code, sem aceitar
endereços, mensagens do fabricante ou conteúdo de sessão.

`configure_video.py --update` recompila e troca somente uma instalação anterior
íntegra com o conjunto exato de arquivos conhecidos. Preserva a versão anterior
em `.local/video-backup-*`; arquivos extras ou hashes inconsistentes bloqueiam a
troca. Uma falha de compilação deixa a versão anterior intacta.

Validação: 57 testes Python e 8 de interface; compilação C com warnings como erros;
testes nativos offline no Wine para formato 0, formato 1, callback inicial sem
init seguido de quadro válido e carregamento do player real. Os testes de quadro
usam pixels sintéticos, não imagens de câmeras. A correção ainda precisa do teste
real do usuário; não se afirma que esse resultado já resolve a recepção P2P.

## Torre de Controle DCS: transmissão e mosaico

O usuário confirmou por captura de tela a recepção de imagem real e, em seguida,
informou que a maioria das câmeras captura normalmente. Algumas informaram
**formato 5, 640×360**. Não se reproduzem aqui IDs, e-mail ou imagens do usuário.
O produto passou a se chamar **Torre de Controle DCS**, com mosaico responsivo,
busca, tela cheia, resumo da sessão e modo foco. Pessoas e carros foram adiados
explicitamente pelo usuário.

O formato 5 segue o ramo de dois planos em `0x1401ae137` do renderer original,
diferente dos códigos planares 0/1. A ponte inclui o caminho Windows NV12 (Y + UV
intercalado), com validação dos tamanhos de Y e UV, separando U/V antes da saída
YUV420. Um fixture colorido U=90/V=180 verificou os bytes de saída e a ordem da
conversão, sem um terceiro plano de entrada. A aceitação nas câmeras reais que
reportaram formato 5 continua pendente; não se tentam outros formatos por adivinhação.

O modo `--stream` mantém um registro/player nativo por câmera e escreve um único
cabeçalho Y4M F5:1, seguido de quadros. O callback limita a saída a cinco quadros/s
sem reinicializar o player. Encerra em mudança de dimensões, falta de quadros por
15 segundos ou limite absoluto de 20 minutos. Não muda parâmetros da câmera.

`live.py` mantém um pipeline Wine → Y4M → FFmpeg → JPEG por câmera. O parser trata
markers fragmentados e vários JPEGs por leitura, limitando cada quadro a 8 MiB.
Só o JPEG mais recente e sua sequência ficam retidos. Tokens vão por stdin,
sem arquivo de sessão, argumentos ou saída do fornecedor. Stop mata os grupos
de processos pertencentes ao pipeline, aguarda término, fecha pipes e apaga o
diretório temporário. Não executa login HTTP novamente.

O servidor mantém até oito conexões nativas no total, com autorização pela lista
da conta e por sessão, sem compartilhar frames entre usuários. Todos os endpoints
são POST com Origin/CSRF e cookie. Cada câmera tem um identificador local de fluxo;
frame/stop com um identificador substituído não acessa nem interrompe o fluxo novo.
Start duplicado devolve o fluxo existente. Uma falha não para as outras câmeras.
O próprio SDK é carregado uma vez por processo/câmera nesta implementação; o
consumo e o comportamento de múltiplos registros reais ainda precisam do teste
no Chromebook, não são inferidos dos fixtures.

Frames são consultados pelo navegador a cada 200 ms, sem bloqueio no endpoint e
sem segredos na URL. Sem consultas por 20 segundos, o watchdog encerra o pipeline.
Logout, novo login, nova consulta de dispositivos, expiração da sessão e shutdown
fecham os fluxos. A página tenta stop em pagehide; inatividade é a salvaguarda se
esse envio não ocorrer. Mais de três segundos sem atualização retiram o selo de
ao vivo, inclusive quando a resposta seguinte fica atrasada.

### Validação desta versão

- 64 testes Python e 13 testes de interface. Pipeline real local com produtor
  sintético e FFmpeg verificou vários JPEGs diferentes pela mesma conexão, limpeza
  de processos, inatividade e expiração. API com fornecedor sintético verificou
  oito slots, autorização de câmera, isolamento entre sessões e parada individual.
- Wine offline (`--network none`): construtor/player real e fixtures de formatos
  0, 1, 5, callback incompleto seguido de válido e seis quadros contínuos distintos.
  Compilação MinGW com warnings tratados como erros. Conversão NV12 conferida
  byte a byte; seis JPEGs distintos gerados pelo FFmpeg.
- Chromium real com API/imagens sintéticas: oito cartões em foco, sem overflow
  horizontal e com o último cartão abaixo de y=746 em viewport 1366×768. Também
  verificado em 1440×1000 e 390×844, sem erros JavaScript. Os padrões de teste
  existem apenas fora do checkout e não são câmeras de demonstração no produto.

Login, listagem e captura real são confirmados pelo usuário. A transmissão
contínua, a estabilidade do mosaico com oito câmeras e o caminho de formato 5
nas câmeras que falharam aguardam o próximo teste dele. Detecção, alertas, áudio,
PTZ, gravação e hospedagem pública continuam fora desta entrega.

## Correção da abertura simultânea do mosaico

O usuário confirmou que todas as câmeras abrem individualmente, mas algumas
falham no mosaico com interrupção genérica e outras com timeout P2P. Isso confirma
compatibilidade individual e falha sob concorrência; não identifica sozinho se
a causa é CPU/memória, negociação de rede ou limite do SDK/provedor.

A revisão encontrou dois problemas de concorrência no código anterior: todos os
workers iniciavam imediatamente e `-threads 1` limitava somente o encoder de saída,
sem limitar os pools de filtros do FFmpeg. A versão atual usa `-filter_threads 1`,
`-filter_complex_threads 1` e `-threads 1` antes e depois da entrada. No mosaico,
preview_width=640 reduz o custo de redimensionamento/JPEG; abertura individual
continua em 960. O fluxo/qualidade na câmera não é alterado.

Uma semáfora global de duas aberturas protege a negociação e a criação inicial
do pipeline. É liberada no primeiro JPEG, em falha ou ao cancelar; o limite de oito
fluxos ativos é separado e permanece. O watchdog conta os 45 segundos de tentativa
somente após obter a vaga, sem penalizar quem aguarda na fila. As consultas de
quadros mantêm a expiração por falta de visualização durante a espera. Parar uma
câmera enfileirada não libera a vaga pertencente a outra câmera.

Apenas o stderr do FFmpeg é drenado e classificado em memória por padrões fixos,
sem retenção em arquivo ou encaminhamento de linhas ao navegador. Saídas do SDK
continuam suprimidas. Falta de recursos do conversor, falha ao abrir encoder,
código de saída do conversor e erro nativo são diferenciados. Uma saída nativa 0
não é mais usada para mascarar a falha do conversor como interrupção inespecífica.
Não foram adicionados retries de login, mudanças de host ou reconexões automáticas.

69 testes Python e 14 de interface passaram. O teste de carga iniciou oito
pipelines locais reais com FFmpeg e fonte YUV sintética 640×360, verificando que
todos receberam pelo menos dois quadros e continuaram abertos, com threads
limitadas. Também foram verificados liberação da vaga no primeiro quadro, cancelamento
na fila sem liberar vaga alheia e preservação do timeout durante espera. Esses
testes não reproduzem as câmeras, a conexão 4G ou o SDK real sob oito registros;
a resolução do problema no Chromebook ainda depende do teste do usuário.

## Formato 5, seleção de qualidade e abertura após login

A investigação posterior corrigiu a hipótese de formato 5 exclusivamente NV12.
No SDK inspecionado, o decodificador H.265 em `0x180021370` escreve também três
ponteiros/planos e seus tamanhos em AVData, compactando Y=largura×altura e U/V=¼.
O código agora prefere os três planos quando válidos; caso contrário, aceita NV12
com UV intercalado e tamanho suficiente. As verificações de dimensões e limites
permanecem. Isso explica um caminho concreto para o erro 20 observado, sem provar
que todos os timeouts de rede tenham a mesma causa.

No cliente, `SendUserDataController::execute` em `0x14014c440` traduz
ctrl_video_FHD/HD/SD para 3/2/1. `PlayerModel::changeDefinition` em `0x140168690`
subtrai um antes de chamar o SDK: FHD=2, HD=1, SD=0. O adaptador usa esses valores
em setDataResource, por opções fixas --stream-fhd/--stream-hd/--stream; nenhum
argumento de conta vai para a linha de comando. Os perfis HD/FHD removem o filtro
local de redução e usam JPEG q=2; Equilibrada preserva os limites 640/960 e q=5.
A resolução física entregue por cada câmera ainda exige confirmação real.

Após um login bem-sucedido, a interface consulta os dispositivos e inicia as
primeiras oito câmeras. Falhas de login/listagem não iniciam vídeo nem repetem o
login. A seleção de qualidade reinicia apenas a câmera escolhida. O navegador
informa naturalWidth/naturalHeight do JPEG decodificado, sem prometer resolução
superior à efetivamente recebida.

Validação desta alteração: 71 testes Python e 16 de interface, incluindo login
com abertura automática, seleção isolada de qualidade e liberação de capacidade
após parâmetro inválido. FFmpeg real preservou 1280×720 no modo original e reduziu
a mesma fonte sintética para 640×360 no mosaico. O adaptador recompilado passou
seis fixtures no Wine com rede desabilitada, incluindo formato 5 de três planos,
NV12 com U/V distintos e seis quadros contínuos. Chromium validou oito cartões,
resolução exibida e ausência de overflow horizontal/erros JavaScript em desktop,
Chromebook e celular, com conta e imagens sintéticas apenas no teste.

## Sessão local contínua e recuperação para uso na TV

A expiração local passa a ser por inatividade: requisições da sessão atualizam
expires e o prazo dos streams. GET /api/status também renova o cookie HttpOnly,
SameSite=Strict com Max-Age=1200; o navegador consulta esse endpoint a cada cinco
minutos sem reconstruir os cartões. A falta de consultas ainda encerra os fluxos
pelo watchdog. Nada é persistido de credenciais ou tokens em disco.

A interface mantém intenção de assistir separada do fluxo atual. Falhas
transitórias iniciam outra conexão da mesma câmera após 5, 10, 20, 40 e no máximo
60 segundos; um quadro recebido zera essa espera. Parar, logout e fechamento da
página removem a intenção e seus timers. Erros de configuração/entrada e sessão
HTTP inválida não repetem o login. O encerramento nativo aos 20 minutos continua
limitado, seguido de nova conexão; não se promete vídeo sem intervalo nessa troca.
O acesso do provedor não é renovado automaticamente e pode exigir novo login.

## Reports e economia de dados

Detecção local MobileNet-SSD via OpenCV DNN, uma inferência por amostra recente
por câmera a cada 5 s, worker único e threads OpenCV limitadas. Fonte pública:
https://github.com/chuanqi305/MobileNet-SSD, revisão
bb17b6c3eef36d80be441ae8e5339be66e8e3b7a. SHA-256 deploy.prototxt:
2d180f723b3109e21f8287f6b3c691390d07b60eed998327cd3259ffa0e50608;
mobilenet_iter_73000.caffemodel:
52eed8be80522c152a17fb56740de705b79881bde1a167e0e747310523685fc7.
Arquivos baixados apenas na configuração; não são versionados. Inferência real
com foto pública de ônibus do repositório Ultralytics retornou veículo e duas
pessoas; não equivale a validar precisão nas câmeras do usuário.

Eventos SQLite separados pelo hash do login bem-sucedido; fotos exigem sessão
Yoosee autenticada correspondente. Registra abertura e, com detector disponível,
presença de pessoa/veículo, caixas e confiança. Intervalo mínimo de 60 s por classe
e câmera; não rastreia identidade nem garante registrar cada objeto distinto.
OCR Tesseract opcional no recorte do veículo sugere padrão brasileiro, não confirma
placa. Retenção em escrita de 30 dias/1.000 eventos por conta. Nenhuma integração
externa de notificação foi ativada, por escolha do usuário.

Economia usa timers por câmera: 5 minutos ativos em cada janela de 30. A pausa
cancela intent/retry, fecha o stream nativo e conserva somente o último JPEG,
marcado como pausado. O monitor não faz heartbeat, portanto não mantém um stream
abandonado vivo nem analisa fotos antigas. Parar/logout/pagehide cancelam timers;
recarga perde as preferências e exige nova ativação. Não há detecção na pausa.
Testes verificam erro nativo de 15 s com retry e cancelamento desse retry na pausa.

Validação final: 77 testes Python e 19 de interface passaram; Chromium verificou
login oculto após autenticação, oito cartões sem sobreposição, visão completa,
Reports com fotos/caixas e largura móvel sem overflow. Casos de teste usam contas
e imagens públicas/sintéticas, não credenciais ou vídeo privado do usuário.

## Reports somente de pessoas

A pedido do usuário, o detector passa a aceitar somente classe VOC 15 (pessoa).
O monitor ignora demais classes mesmo se retornadas por um detector substituto.
Removidos OCR, execução de Tesseract e exibição de placas/veículos. O modelo com
hash já instalado continua compatível. O esquema SQLite conserva a coluna plate
por compatibilidade com bancos existentes, sem a preencher ou retornar na API.
A listagem filtra pessoa/abertura antes de paginar e o acesso a imagens bloqueia
registros antigos de veículos; nenhum histórico é apagado nesta migração.

## Acesso externo, Reports somente de pessoas e preferências 8/12

Removida a gravação de eventos opened, e a listagem filtra exclusivamente person
antes de paginar, mantendo o histórico antigo oculto. A tabela preferences no
mesmo banco salva economy_ids e mosaic_limit por dono; API autenticada valida
câmeras conhecidas e limites 8/12. Preferências são restauradas após login e
reload sem persistir credenciais do provedor. O limite global de conexões passou
a 12; o semáforo de duas negociações iniciais continua. Não há validação de 12
sessões reais do SDK nesta nuvem.

access.py armazena hash scrypt com salt aleatório e controla tokens de entrada
em memória, com renovação por atividade (12 h) e cinco tentativas/minuto globais.
Nenhuma senha padrão consta no repositório. O usuário informa a senha no primeiro
uso no computador onde o túnel será executado. remote_access.py lança cloudflared,
extrai uma URL estritamente trycloudflare.com, configura origem HTTPS exata e
fecha os processos ao encerrar. Não encaminha logs brutos do túnel.

O serviço continua exclusivamente em loopback. Modo público exige gate e aceita
somente o Host configurado com X-Forwarded-Proto=https; o Origin das operações
POST deve corresponder à origem exata. Cookies públicos de entrada e conta usam
Secure, HttpOnly e SameSite=Strict. APIs/fotos exigem entrada no sistema, e depois
mantêm sessão de conta e CSRF. Nenhum vídeo ou foto foi publicado em um túnel real
nos testes; HTTPS/proxy foram simulados por headers contra servidor local.

## Detecção por câmera, clipes e retenção

preferences inclui detection_ids, padrão vazio. Apenas streams habilitados são
amostrados. A atualização autenticada da preferência propaga a flag aos streams
da mesma conta. UI salva/restaura o botão por câmera. Reports tem abas Fotos e
Vídeos com paginação separada; não grava nem exibe opened.

clips.py reutiliza o último JPEG fresco, não faz heartbeat e não abre SDK extra.
Um encoder FFmpeg H.264 por câmera gera até 120 s, sem áudio, 2 fps, uma thread,
largura limitada a 1280. No máximo 12 gravações concorrentes. A existência de
pessoa não dispara outro clipe enquanto o anterior está ativo. Falha aguarda 60 s
antes de nova tentativa. Encoders possuem watchdog, fechamento de stdin e
verificação ffprobe; só arquivos finalizados são disponibilizados. Paradas e
pausa de economia produzem trecho parcial quando possível. Vídeos temporários
interrompidos são removidos na recuperação após reinício.

Metadados de vídeos no SQLite e arquivos em reports/videos com nomes aleatórios.
A API exige gate (quando configurado), conta correspondente e Origin/CSRF para
listar. GET de MP4 exige conta e dono e suporta Range validado para reprodução.
Manutenção a cada 60 s e limpeza em operações de armazenamento removem MP4/linhas
após 5 dias e fotos após 30. Fotos mantêm limite de 1.000 por conta. SQLite reutiliza
páginas após apagar BLOBs. Gravação requer pelo menos 256 MB livres e encerra quando
arquivo passa de cerca de 32 MB. Os arquivos são locais e não enviados para IA.

Validação final desta versão: 89 testes Python e 22 de interface, incluindo gate
HTTPS simulado, limite de tentativas, isolamento de fotos/vídeos, Range de MP4,
preferências persistentes 8/12 e detecção, câmeras desabilitadas ignoradas, geração
real H.264 com duração reduzida de teste e finalização parcial em pausa, exclusão
após 5/30 dias e cancelamento dos timers de economia. Chromium validou gate real
local com senha de teste, mosaico de 12 sem sobreposição e reprodução H.264 na aba
Vídeos. Contas/câmeras do teste são simuladas; nenhum túnel público foi iniciado.

## Serviços de inicialização

configure_startup.py gera dcs-control.service e dcs-tunnel.service como usuário
não root, com HOME explícito, caminhos/argumentos escapados para systemd,
Restart=always, RestartSec=5 e KillMode=control-group. Usa o túnel permanente
existente, não o gerador de URLs temporárias. Antes de instalar, confere gate,
configuração do túnel/domínio/porta, presença de systemd e conflito com servidor
manual. Arquivos de serviço não contêm senhas nem tokens; cloudflared lê seu
arquivo de configuração usual. --install solicita sudo apenas para instalação e
gestão de serviços; --uninstall remove os dois serviços sem excluir dados locais.

A instalação não foi executada nesta nuvem e não altera o ChromeOS hospedeiro.
Serviços só iniciam quando o ambiente Linux iniciar; não existe promessa de
inicialização da VM Linux pelo ChromeOS. Sessão Yoosee e monitoramento continuam
dependendo de login e de página aberta após reiniciar, conforme arquitetura atual.

Validação: três testes do instalador verificam usuário, reinício automático,
escaping e leitura do config sem credenciais. systemd-analyze verify aprovou os
dois arquivos gerados, sem instalação/inicialização de serviços na nuvem. A suíte
Python completa passou com 92 testes. A configuração real depende do systemd do
Chromebook e deve ser aplicada executando o instalador naquele computador.

## Resposta HTML do túnel durante consultas de câmera

A captura do usuário mostrou Failed to fetch e HTML (!DOCTYPE) onde o painel
esperava JSON, junto com timeouts P2P. Isso comprova falhas de transporte/resposta,
mas não determina se houve queda do processo, saturação, túnel ou internet.
readResponse trata JSON inválido sem exibir HTML/logs e classifica a resposta como
falha transitória; respostas 5xx mantêm código HTTP. As tentativas existentes são
preservadas. Teste simula HTML de gateway 502, verifica mensagem de conexão,
ausência de conteúdo bruto e nova tentativa. 23 testes de interface passaram.
A causa no Chromebook ainda exige comparar localhost e domínio e checar serviços.


## Background monitoring and Telegram (21/10/2026)

Enabled person-detection sources are now owned by a server worker, independently
of browser handles. Economy windows remain five minutes active per thirty-minute
cycle. Native streams and recorders enforce the window deadline. Camera account
authorization remains in memory and requires login after a server restart.

Telegram delivery is opt-in per account, using a bounded asynchronous queue and
HTTPS requests to the fixed api.telegram.org host without redirects. The bot token
is stored in the private local SQLite database and omitted from API responses and
logs. Notification failures do not stop local detection. Photo alerts link to the
authenticated Reports video list, rather than exposing private video files.

Validation: final Python suite passed all 105 tests, including API security and
Telegram delivery failure isolation. JavaScript suite
passed all 25 tests. Chromium mobile QA verified configuration, token clearing,
test submission and the video tab link with simulated APIs. No Telegram message
was sent and no real camera was accessed in this environment for these changes.

## Qualidade, detecção e aprendizado facial — 22/10/2026

O adaptador passou de 5 para alvo de 10 fps, JPEGs usam menor compressão e os
clipes H.264 são amostrados a 10 fps, CRF 22, largura até 1920 e teto aproximado
96 MiB. FPS exibido é medido nos quadros recebidos; geometria vem do JPEG. Não se
trata de resolução do sensor nem de medição de latência ponta a ponta.

A análise de pessoas usa quadros distintos a cada segundo, limiar 0,55 e segunda
escala para imagens largas sem resultado inicial. O modelo MobileNetSSD instalado
foi executado em foto pública de teste, retornando duas pessoas em cerca de 78ms
neste ambiente; não representa desempenho garantido do Chromebook ou cobertura
de todos os casos. Falhas por câmera ficam isoladas. Um teste HTTP de concorrência
confirma que uma câmera lenta não bloqueia respostas das demais na mesma conta.

O cadastro facial usa YuNet 2023mar e SFace 2021dec. Os hashes vieram dos ponteiros
LFS públicos do OpenCV Zoo. Apenas nomes confirmados por usuário alimentam a base
local de exemplos. Descritores são normalizados, separados por conta e não saem
na API. Sugestões usam cosseno 0,55 com margem 0,08 entre nomes distintos. Não há
retreinamento de pesos, identificação garantida, proteção contra apresentação de
fotos nem uso para decidir acesso físico.

O C compilou com avisos tratados como erro, usando Zig para destino Windows x64
sem executar DLL do fabricante. O instalador do usuário continua usando MinGW.
O download de pesos YuNet/SFace foi bloqueado pela rede deste ambiente nos hosts
GitHub Media e Hugging Face; por isso o reconhecimento de rostos reais não foi
validado aqui. O instalador verifica hashes e o painel mantém mensagem de modelos
ausentes, preservando o detector de pessoas. O teste OpenCV de qualidade de recorte
usa saídas simuladas de landmarks/descritores e pixels sintéticos; testes de base
cobrem aprendizado manual, correção, exclusão, ambiguidades, retenção e isolamento.
Chromium validou nomes, ativação/desativação, layout móvel, ampliação, FPS e Reports
na mesma aba, com câmeras simuladas. Nenhuma câmera real ou mensagem Telegram foi
utilizada durante esta atualização.

Validação final: suíte de 115 testes Python sem falhas (um teste de pixels pulado no Python
sem OpenCV; executado e aprovado separadamente no ambiente com OpenCV), além de
27 testes JavaScript e a navegação Chromium descrita acima.

## Cartão, pré-evento, retenção e diagnóstico facial — 28/10/2026

A inspeção de exports do DLL confirmou `setPlaybackDataResource`, `startRecord`,
`stopRecord` e `setTimeListener`. As chamadas de reprodução do cliente Windows
usam valores derivados de `QDateTime::toMSecsSinceEpoch` (por exemplo, chamada em
0x140123157 salva em +0x170, usado pela reprodução em 0x1401233e0). O adaptador
passa intervalos em milissegundos, registra a reprodução usando o gravador do SDK
e exige timestamps absolutos coerentes, além de validar arquivo e duração.

O callback usa o layout MSVC observado (objeto std::function de 64 bytes, ponteiro
de implementação em +0x38). O exportador é isolado em processo e tem limites de
tempo, tamanho e espaço livre. Essa compatibilidade ABI e o acesso ao cartão
continuam **experimentais e sem teste em câmera real**; a compilação não comprova
que um firmware aceite o intervalo ou forneça callbacks de horário. Respostas
incompatíveis preservam o vídeo local. Não há uso de APIs de exclusão do cartão.

Uma fila limitada a 12 itens, um exportador e o semáforo global de 12 conexões
limitam trabalho adicional. Economia ou detecção desativada impedem novas buscas;
o processo ativo é encerrado quando a janela termina. O vídeo local é gravado
primeiro; somente após validação o arquivo é trocado por outro nome numa transação.
H.264 é remultiplexado sem reduzir FPS; outros codecs usam conversão H.264 sem
forçar uma taxa artificial. O teste com vídeo sintético a 25fps confirmou a
preservação dessa taxa. Testes também rejeitam horários de outro evento, verificam
que tokens ficam fora dos argumentos e mantêm o arquivo local em caso de falha.

O pré-evento local usa ring buffer de cinco segundos/12 MiB por câmera habilitada,
com timestamps monotônicos. Um teste de codificação conferiu duração e cor do
primeiro quadro para comprovar que quadros anteriores entram antes dos atuais.
Retenção passou a quinze dias para vídeos; fotos permanecem em trinta.

A análise facial não depende mais de uma detecção de corpo positiva no mesmo
quadro. Foram revisados margem da região, resolução mínima (40px), limiar do
detector e nitidez, mantendo o classificador de identidade conservador. Diagnósticos
por conta mostram detecção desativada, modelo ausente e motivo de rejeição. Erros
faciais não interrompem o registro de pessoas e são exibidos sem detalhes internos.

Chromium conferiu origem dos vídeos, estado de fallback por horário, retenção,
diagnósticos, cadastro e saída de rostos, além de ajuste contain para 4:3 e retrato.
Não foi identificado filtro de crop no layout ou conversor. Diferenças de campo
visual entre SD/HD, lentes e aplicativo precisam ser comparadas nas câmeras reais;
o tamanho do OSD não é evidência suficiente de crop pelo painel.

Validação desta versão: 123 testes Python sem falhas, com um teste de pixels
pulado no Python padrão; o conjunto de 15 testes de rostos/Reports passou no
ambiente com OpenCV. Também passaram 27 testes JavaScript, as verificações Chromium
e a compilação Windows x64 com avisos tratados como erro. Nenhuma câmera real
nem conta Telegram foi acessada durante os testes desta atualização.


## Revisão de estabilidade e cartão — 30/10/2026

O vídeo fornecido pelo usuário tem H.264 640×360, 453 quadros e duração de 45,3s,
a 10 FPS nominais. Há mudanças irregulares entre imagens e no relógio sobreposto;
a taxa nominal não comprova dez imagens novas por segundo. A cena parada também
não permite atribuir todos os intervalos à rede. A revisão separa captura JPEG de
codificação e usa os horários monotônicos de chegada para montar uma linha do
tempo VFR. Isso preserva lacunas, sem reconstruir movimento perdido.

O transporte do painel passa a MJPEG autenticado, compartilhando a mesma fonte
por câmera, com consultas de saúde independentes. O monitor do servidor também
encerra fontes estagnadas sem depender do watchdog interno ou de uma aba aberta.
Ampliar uma imagem não eleva automaticamente a definição nem reinicia a fonte.

Na DLL inspecionada, `addPlaybackListListerner` guarda uma função com argumento de
tipo e uma mensagem contendo string MSVC e vetor de registros de 48 bytes. Os
dois primeiros uint64 de cada registro são tratados como início/fim somente após
validar formato, tamanho e intervalo plausível em milissegundos Unix. O adaptador
limita a 512 registros e não devolve nomes de arquivo, tokens ou estruturas brutas.
A lista usa spool em arquivo para não bloquear a saída do subprocesso.

O cliente Windows configura a fonte com os limites do arquivo e usa
`seekPlaybackPosition` com o par de horários desejado. O adaptador reproduz essa
sequência e exige confirmação do relógio de reprodução antes de iniciar a cópia.
A consulta manual tem janela máxima de uma hora; a cópia tem até dois minutos.
Nenhum comando de exclusão ou formatação é chamado. A substituição automática
continua preservando o clipe local em qualquer falha de validação.

Esses layouts privados e o posicionamento ainda exigem validação em hardware real;
compilar o adaptador e exercitar fixtures não confirma suporte em todos os firmwares.
Falha da consulta não é evidência de cartão vazio. Mensagens distinguem consulta,
posicionamento, ausência de quadros e horário não confirmado.

O cadastro facial foi removido da aplicação. A webcam é uma fonte V4L2 local,
explicitamente habilitada, com o mesmo monitor de economia e detecção de pessoas.
Não usa getUserMedia do visitante e não é exposta como fonte de cartão.


### Correção do retorno da consulta — 30/10/2026

O teste real mostrou `list_unavailable` apesar de gravações acessíveis no Yoosee.
A revisão da DLL encontrou uma falha no nosso tratamento do retorno: diferentemente
de Register e seek, `getPlaybackList` retorna o identificador assíncrono da solicitação,
não um código de sucesso zero. Em 0x180032190, o resultado de 0x180037760 é registrado
quando não zero (0x180032271..0x1800322a9). O envio em 0x1800607d0 gera um identificador
aleatório de 31 bits, armazenado no pacote em +0x1dc e devolvido ao chamador.
O adaptador anterior encerrava com 34 para esses identificadores positivos, antes
de esperar a lista. Agora aguarda a resposta quando o identificador é positivo.
Zero/negativo viram `list_request_rejected` (37); callback recebido com estrutura
não reconhecida vira `list_response_unsupported` (38); ausência de callback após
18 segundos continua `list_unavailable` (34). Nenhum resultado presume cartão vazio.
A correção é aplicada à consulta manual e à busca automática para backup.
A regressão exercita o contrato C compilado com uma consulta falsa, incluindo IDs
positivos, rejeições e parâmetros de intervalo. Hardware real continua necessário
para confirmar a próxima etapa da listagem/reprodução.


### Unidades do relógio e posição de apresentação — 30/10/2026

O usuário confirmou listagem real de arquivos contíguos de cerca de 64 segundos,
mas o backup falhou com horário não confirmado. A investigação do callback do
cliente Windows encontrou o vtable instalado em 0x140121a67 (0x1405b1af8), invoke
0x14011c150 e lambda 0x14011a8c0. Em 0x14011a8f5..0x14011a90a, o valor recebido é
dividido por 1.000.000 antes de chamar QDateTime::setTime_t. Logo, o PTS entregue
ao listener está em microssegundos Unix. O filtro antigo aceitava apenas a faixa
de milissegundos e descartava o relógio válido. A normalização agora aceita o PTS
em microssegundos e mantém milissegundos plausíveis, rejeitando relógios relativos.

Outra diferença é seekPlaybackPosition: o segundo horário define a posição da
apresentação. O SDK o multiplica por 1.000 em 0x180028dcc antes de atualizar o
relógio interno em microssegundos. No primeiro seek do PC, 0x14012315d/164 gravam
o mesmo horário ms em ambos os campos usados em 0x1401232ab/b2. A revisão passa
o início desejado em ambos, e não o fim do clipe como segundo argumento.
A gravação encerra pelo relógio normalizado da reprodução, com limite de espera.

O backend planeja a cobertura do intervalo nos arquivos listados, exporta cada
parte e concatena com cópia de vídeo quando codec e dimensões são compatíveis.
Rejeita lacunas, formatos divergentes e excesso de partes. Limites de tempo,
espaço e Economia continuam aplicados. A mesma função é usada no backup manual
e automático; o vídeo local permanece até validar o resultado completo.
No formulário, datetime-local agora conserva segundos e milissegundos, corrigindo
o arredondamento indevido ao selecionar uma linha com início no meio do minuto.
Testes C compilados verificam o contrato de unidades e posicionamento; testes
FFmpeg verificam concatenação real a 25 FPS; teste de navegador simulado confirma
a seleção exata no fuso America/Sao_Paulo. Não há alteração por tentativa de fuso.


### Reprodução inicial, callbacks parciais e diagnóstico — 30/10/2026

Os novos testes do usuário mostraram falhas intermitentes de lista, ausência de
quadros e relógio não confirmado. A revisão dos chamadores de
setPlaybackDataResource no PC (0x1401233cb..0x1401233e0) mostrou que ele usa os mesmos
campos 0x170/0x178 do seek. No caminho inicial, ambos recebem o mesmo instante
selecionado. Portanto, o segundo argumento de horário também não é o fim do arquivo
na abertura inicial. O adaptador agora abre no início desejado nos dois campos e
só tenta seek adicional se a primeira abertura não confirmar o relógio.

O callback de lista com tipo 1 é montado pelo processamento de timeout/retorno
parcial do SDK: 0x180037f30 compara o tempo do pedido mais oito segundos e despacha
0x180034dd0 usando o que recebeu. Não é, por si só, formato desconhecido. O protocolo
privado passa a sinalizar SDList completo/parcial; há uma única repetição em caso
de expiração/parcial, sem presumir cartão vazio. O modo --archive-known recebe
limites numéricos já validados pela consulta e não consulta de novo a cada parte.
A abertura e o posicionamento continuam sujeitos à validação de horário e quadros.

O planejamento anterior rejeitava até 25 ms entre o último quadro de um arquivo e
o primeiro do seguinte. A revisão permite no máximo 250 ms por limite e 1s total,
registrando sd_gap_seconds no Reports; não cria quadros para preencher intervalos.
Uma lacuna maior ou cobertura apenas parcial continua preservando o vídeo local.

SDFAIL1 contém somente código/etapa, tipo de callback, quantidade de registros,
contagem/unidade do relógio, diferença em ms do início pedido, contagem de quadros
e motivo numérico de rejeição do quadro. O backend aceita apenas esse formato fixo,
nunca stderr do fornecedor, e expõe o diagnóstico somente ao proprietário do job
ou vídeo. Exemplos C compilados e fixtures de vídeo verificam os contratos, mas a
reprodução real ainda requer teste com as câmeras do usuário.


### Quadros confirmados e finalização parcial — 30/10/2026

O teste real de Portão Fundo retornou etapa gravação, 853 quadros e 853 callbacks,
com último horário 56,762s após o início. A janela selecionada tinha 63,960s;
portanto faltavam cerca de 7,198s no fim e a regra anterior descartava a cópia.
Isso confirma entrega de quadros e relógio, mas não permite afirmar se a causa é
fim do arquivo, pausa P2P ou reprodução abaixo da cadência em tempo real.

A captura agora segue progresso do relógio, com até 15s sem avanço e prazo global
fornecido pelo backend no modo conhecido. Reserva tempo para finalizar o arquivo
antes do limite externo. O primeiro/último horário são capturados antes de chamar
stopRecord, evitando contabilizar quadros exibidos depois do fim da gravação.

SDPART informa um intervalo parcial confirmado e a razão numérica de término;
SDTIME continua reservado à cobertura completa. O backend verifica intervalo,
duração e decodificação. Uma parte confirmada não vira um clipe completo por
relaxamento silencioso da verificação. Na detecção automática é armazenada em uma
linha separada, com source sd_partial, preservando o fallback local. O Reports
mostra archive_start/archive_end, status parcial e link de download.
Fixtures C reproduzem o caso 56,762/63,960 e rejeitam horários de outro dia; fixtures
FFmpeg verificam que a cópia parcial é reproduzível e não substitui o original.


## Diagnóstico estruturado e retomada por evidência — 30/10/2026

O usuário confirmou uma cópia parcial de 11s em quatro tentativas manuais. Isso
comprova obtenção de arquivo reproduzível, mas não demonstra que todas as falhas
sejam de conectividade. A revisão repete até seis vezes por parte, com esperas de
1/2/4/8/8 segundos, e continua do último horário confirmado mais 1 ms para evitar
repetir o último quadro da parte anterior. Há orçamento global de tempo e a janela
de Economia limita cada subprocesso. Partes precisam passar em ffprobe, verificação
de intervalo/duração, codec e dimensões. Prefixos válidos são preservados quando
as tentativas seguintes falham ou a janela termina. Nenhuma parte faltante é
preenchida com quadros artificiais. O modo conhecido evita repetir a consulta de
lista a cada processo de reprodução.

O botão Copiar logs usa uma rota autenticada, com proteção de origem, gate e CSRF.
A exportação é por conta e reúne dados explicitamente selecionados. Não coleta
stdout/stderr brutos do SDK, tokens, senhas, cookies, conta de login, caminhos
privados ou imagens. O destino é a área de transferência local; não envia nada
a um serviço de análise. Há fallback de seleção manual quando Clipboard API falha.

O histórico estruturado usa fila limitada de 512 eventos, gravação em lote e base
privada do Reports. A escrita não bloqueia o watchdog das câmeras. Retenção de
leitura de sete dias e limite global de 10.000 eventos; exporta até 120 da conta.
Os contadores indicam dados descartados ou falhas de persistência. A amostra inclui
recursos do servidor, estado/FPS/resolução, diferenças entre painel e fonte,
Economia, detecção, quedas, tentativa do cartão, validação do arquivo e últimos
vídeos. Detalhes aceitam somente campos numéricos e códigos de uma lista fixa.

As estatísticas agrupam quedas e resultados finais por câmera. Cópias completas,
parciais e falhas são separadas; espera por falta de vaga, cooldown ou Economia não
entra como tentativa de cópia malsucedida. O relatório aponta FPS baixo observado,
quedas repetidas, baixa conclusão do cartão e disco livre. Trata-se de evidência
para comparar versões e orientar ajustes, sem retreinar modelos ou modificar
qualidade e código automaticamente. Histórico anterior de quedas não é reconstruído.

Testes verificam persistência, isolamento por conta, ausência de credenciais,
limite de tentativas, recuperação após falha, retomada sem reiniciar o prefixo,
pausa por Economia, Clipboard API/fallback e estatísticas. Chromium confirma a
exportação e o progresso no Reports. A estabilidade real ainda depende de nova
observação nas câmeras do usuário com o diagnóstico exportado.
