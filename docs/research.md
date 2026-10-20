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
