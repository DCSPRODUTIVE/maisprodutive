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
