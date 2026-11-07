package br.com.maisprodutive.torrecontrole;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Small TV launcher. Silk owns TLS, playback, cookies and remote navigation. */
public final class MainActivity extends Activity {
    private static final String PANEL = "https://cameras.maisprodutive.com.br/";
    private static final String SILK = "com.amazon.cloud9";
    private TextView message;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        LinearLayout layout = new LinearLayout(this);
        layout.setOrientation(LinearLayout.VERTICAL);
        layout.setGravity(Gravity.CENTER);
        layout.setPadding(48, 24, 48, 24);
        layout.setBackgroundColor(Color.rgb(11, 18, 25));
        TextView title = new TextView(this);
        title.setText("TORRE DE CONTROLE DCS");
        title.setTextSize(28);
        title.setTextColor(Color.rgb(66, 216, 187));
        title.setGravity(Gravity.CENTER);
        layout.addView(title);
        message = new TextView(this);
        message.setText("Abrindo suas câmeras no Amazon Silk…");
        message.setTextColor(Color.WHITE);
        message.setTextSize(18);
        message.setGravity(Gravity.CENTER);
        message.setPadding(0, 24, 0, 24);
        layout.addView(message);
        Button open = new Button(this);
        open.setText("Abrir câmeras");
        open.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View view) { openPanel(); }
        });
        layout.addView(open);
        setContentView(layout);
        open.requestFocus();
        if (state == null) openPanel();
    }

    private void openPanel() {
        Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(PANEL));
        intent.addCategory(Intent.CATEGORY_BROWSABLE);
        intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        intent.setPackage(SILK);
        try {
            startActivity(intent);
            finish();
        } catch (ActivityNotFoundException | SecurityException missingSilk) {
            // Other Fire/Android TV browser only if Silk is unavailable.
            intent.setPackage(null);
            try {
                startActivity(intent);
                finish();
            } catch (ActivityNotFoundException | SecurityException noBrowser) {
                message.setText("Instale ou habilite o Amazon Silk na loja do Fire TV.\nDepois selecione Abrir câmeras.");
                // Keep the focusable retry button; do not loop or weaken HTTPS.
            }
        }
    }
}
