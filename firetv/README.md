# Torre de Controle para Fire TV

Aplicativo Android de acesso direto, preparado para o Fire TV Stick HD com Fire OS 7.
O nome na lista de aplicativos é **Torre de Controle**. O APK tem ícone e banner
para TV, suporta controle remoto e não pede permissões de câmera, microfone,
armazenamento ou rede. Ele abre `https://cameras.maisprodutive.com.br/` no **Amazon
Silk**, que já foi validado pelo proprietário na TV. O painel, Reports, TLS e cookies
continuam no navegador; não há uma segunda reprodução nem outra conta de câmera.

Esta versão é um acesso pelo ícone, não um novo player nativo. Não altera o servidor,
a captura das câmeras nem a configuração de detecção/Economia. Não precisa reiniciar
o serviço nem recompilar o adaptador. Se não houver navegador compatível, mostra
uma instrução de instalação do Silk e um botão de tentativa controlável pelo controle.

## Instalar pelo computador já autorizado via ADB

Com o computador e a TV na mesma rede (IP atual do Fire TV: `192.168.0.15`):

```bash
cd ~/maisprodutive
git pull
adb connect 192.168.0.15:5555
adb -s 192.168.0.15:5555 install -r firetv/dist/torre-de-controle-firetv.apk
adb -s 192.168.0.15:5555 shell am start -n br.com.maisprodutive.torrecontrole/.MainActivity
```

Aceite a autorização na TV se for solicitada. O comando de instalação deve retornar
`Success`. Se o IP mudar, substitua pelo IP atual em Configurações → Meu Fire TV →
Sobre → Rede. O ambiente de desenvolvimento em nuvem não tem acesso direto à LAN;
os comandos ADB devem ser executados no computador que já se conectou à TV.

Depois: **Home → Seus aplicativos → Torre de Controle**. No menu do aplicativo,
use **Mover/Mover para a frente**, se disponível, para facilitar o acesso diário.
O login já salvo no Silk é aproveitado. Caso ainda seja necessário entrar, marque
as duas opções de manter o aparelho autorizado. O aplicativo não contém senhas.

## Comando de voz no controle

Segure o botão do microfone e diga **“Abrir Torre de Controle”**. O nome do aplicativo
foi registrado exatamente assim no Android. A instalação por APK, porém, **não
registra um aplicativo no catálogo de voz da Amazon**. A Alexa pode não reconhecer
um app instalado fora da Appstore; não é possível garantir esse comando apenas
mudando o nome do APK. O nome “DCS” permanece no ícone, mas não é necessário na frase.

Se a Alexa não reconhecer, o ícone continua funcionando. “Abrir Amazon Silk” pode
servir como alternativa, mantendo o painel como página/aba do navegador. Uma rotina
personalizada só é alternativa se o aplicativo Alexa da conta oferecer ação compatível
de abertura no Fire TV; precisa ser validada no aparelho. Publicação na loja e uma
integração específica de voz exigem outro fluxo e não estão incluídas nesta versão.

## Compilar e verificar

O APK assinado está em `dist/torre-de-controle-firetv.apk`; `dist/SHA256SUMS` permite
verificar a integridade:

```bash
cd firetv/dist
sha256sum -c SHA256SUMS
```

Para desenvolver, use um JDK com `java` e `keytool`, uma plataforma Android API 28
ou superior e Android SDK Build Tools com `aapt`, `zipalign` e os jars de D8/DX e
apksigner. A compilação foi verificada com as ferramentas oficiais 28.0.3:

```bash
python3 firetv/build.py \
  --platform "$ANDROID_SDK_ROOT/platforms/android-28/android.jar" \
  --tools "$ANDROID_SDK_ROOT/build-tools/28.0.3"
```

O script compila Java, gera DEX, empacota/alinha o APK e verifica assinaturas v1/v2.
A chave e sua senha ficam somente em `.local/firetv-signing/`, ignoradas pelo Git,
com permissões privadas; nunca são embutidas no APK. Preserve essa chave para
atualizações com a mesma assinatura. Não use a chave deste aplicativo para outros
produtos. O aplicativo não tem dados próprios de login: eles continuam no Silk.

A assinatura, alinhamento, manifesto, recursos de TV e o conteúdo DEX foram
verificados. Instalação, controle e reconhecimento pela Alexa ainda precisam ser
confirmados no Fire TV físico, que está na rede do proprietário.
