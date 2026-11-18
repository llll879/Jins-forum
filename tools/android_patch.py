#!/usr/bin/env python3
"""Патчит сгенерированный Capacitor-проект (android/app/src/main):
  1) AndroidManifest.xml — разрешения камера / микрофон / уведомления / вибрация;
  2) MainActivity.java   — мост window.ExgNative: has / request / openSettings / notify / media / mediaStop;
  3) MusicService.java   — фоновая служба плеера: уведомление с обложкой и кнопками ◀◀ ▶/❚❚ ▶▶ ✕, экран блокировки, гарнитура.
Клиент (forum.src.html, EXGPerm) вызывает мост, и Android показывает системное окно «Разрешить?».
Запуск (из android-app):  python3 ../tools/android_patch.py android/app/src/main
"""
import glob, os, re, sys

main = sys.argv[1] if len(sys.argv) > 1 else "android/app/src/main"

# ---------- манифест ----------
mp = os.path.join(main, "AndroidManifest.xml")
m = open(mp, encoding="utf-8").read()
perms = [
    '<uses-permission android:name="android.permission.CAMERA" />',
    '<uses-permission android:name="android.permission.RECORD_AUDIO" />',
    '<uses-permission android:name="android.permission.MODIFY_AUDIO_SETTINGS" />',
    '<uses-permission android:name="android.permission.POST_NOTIFICATIONS" />',
    '<uses-permission android:name="android.permission.VIBRATE" />',
    '<uses-permission android:name="android.permission.WAKE_LOCK" />',
    '<uses-permission android:name="android.permission.FOREGROUND_SERVICE" />',
    '<uses-permission android:name="android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK" />',
    '<uses-feature android:name="android.hardware.camera" android:required="false" />',
    '<uses-feature android:name="android.hardware.camera.autofocus" android:required="false" />',
    '<uses-feature android:name="android.hardware.microphone" android:required="false" />',
]
add = [p for p in perms if re.search(re.escape(re.search(r'android:name="([^"]+)"', p).group(0)), m) is None]
if add:
    m = m.replace("<application", "\n    ".join(add) + "\n    <application", 1)
svc = '<service android:name=".MusicService" android:exported="false" android:foregroundServiceType="mediaPlayback" />'
if "MusicService" not in m:
    m = m.replace("</application>", "    " + svc + "\n    </application>", 1)
open(mp, "w", encoding="utf-8").write(m)
print("manifest: добавлено", len(add), "строк + служба плеера")

# ---------- MainActivity ----------
found = glob.glob(os.path.join(main, "java", "**", "MainActivity.java"), recursive=True)
if not found:
    sys.exit("MainActivity.java не найден — сначала выполните npx cap add android")
jp = found[0]
pkg = re.search(r"^package\s+([\w.]+);", open(jp, encoding="utf-8").read(), re.M).group(1)

JAVA = """package %PKG%;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.webkit.JavascriptInterface;
import androidx.annotation.NonNull;
import androidx.core.app.ActivityCompat;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;
import com.getcapacitor.BridgeActivity;
import org.json.JSONObject;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/** Мост для веб-клиента: window.ExgNative. Системные окна разрешений вызываются отсюда. */
public class MainActivity extends BridgeActivity {
    private final Map<Integer, String> pending = new HashMap<>();
    private int nextCode = 4100;
    private int nid = 1;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getBridge().getWebView().addJavascriptInterface(new Native(), "ExgNative");
    }

    private String permFor(String kind) {
        switch (kind) {
            case "mic": return Manifest.permission.RECORD_AUDIO;
            case "cam": return Manifest.permission.CAMERA;
            case "notif": return Build.VERSION.SDK_INT >= 33 ? Manifest.permission.POST_NOTIFICATIONS : null;
            default: return null;
        }
    }

    private boolean granted(String kind) {
        if (kind.equals("notif") && Build.VERSION.SDK_INT < 33) {
            return NotificationManagerCompat.from(this).areNotificationsEnabled();
        }
        String p = permFor(kind);
        if (p == null) return true;
        return ContextCompat.checkSelfPermission(this, p) == PackageManager.PERMISSION_GRANTED;
    }

    private void done(final String id, final boolean ok) {
        runOnUiThread(new Runnable() {
            public void run() {
                try {
                    getBridge().getWebView().evaluateJavascript(
                        "window.__exgPermDone&&window.__exgPermDone('" + id + "'," + ok + ")", null);
                } catch (Exception ignored) { }
            }
        });
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        String id = pending.remove(requestCode);
        if (id == null) return;
        boolean ok = grantResults.length > 0;
        for (int r : grantResults) if (r != PackageManager.PERMISSION_GRANTED) ok = false;
        done(id, ok);
    }

    public class Native {
        @JavascriptInterface
        public boolean has(String kind) {
            return granted(kind);
        }

        /** kinds — через запятую: mic,cam,notif. Результат придёт в window.__exgPermDone(id, ok). */
        @JavascriptInterface
        public void request(final String kinds, final String id) {
            runOnUiThread(new Runnable() {
                public void run() {
                    List<String> need = new ArrayList<>();
                    for (String k : kinds.split(",")) {
                        k = k.trim();
                        String p = permFor(k);
                        if (p != null && !granted(k) && !need.contains(p)) need.add(p);
                    }
                    if (need.isEmpty()) {
                        boolean ok = true;
                        for (String k : kinds.split(",")) if (!granted(k.trim())) ok = false;
                        done(id, ok);
                        return;
                    }
                    int code = nextCode++;
                    pending.put(code, id);
                    ActivityCompat.requestPermissions(MainActivity.this, need.toArray(new String[0]), code);
                }
            });
        }

        /** Если пользователь отказал навсегда — системное окно уже не появится, ведём в настройки приложения. */
        @JavascriptInterface
        public void openSettings() {
            runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        Intent i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS);
                        i.setData(Uri.fromParts("package", getPackageName(), null));
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                    } catch (Exception ignored) { }
                }
            });
        }

        /** Состояние плеера из JS: {id,title,artist,img,playing,pos,dur(мс)} → уведомление в шторке и на экране блокировки. */
        @JavascriptInterface
        public void media(final String json) {
            runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        JSONObject o = new JSONObject(json);
                        MusicService.show(MainActivity.this, o.optString(\"id\"), o.optString(\"title\"), o.optString(\"artist\"),
                            o.optString(\"img\"), o.optBoolean(\"playing\"), o.optLong(\"pos\"), o.optLong(\"dur\"));
                    } catch (Exception ignored) { }
                }
            });
        }

        @JavascriptInterface
        public void mediaStop() {
            runOnUiThread(new Runnable() {
                public void run() {
                    MusicService s = MusicService.inst;
                    if (s != null) s.finish();
                }
            });
        }

        /** Системное уведомление (когда приложение свёрнуто). */
        @JavascriptInterface
        public void notify(String title, String body, String href) {
            try {
                if (!granted("notif")) return;
                NotificationManager nm = (NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE);
                if (Build.VERSION.SDK_INT >= 26) {
                    nm.createNotificationChannel(new NotificationChannel("exg_main", "Уведомления форума", NotificationManager.IMPORTANCE_DEFAULT));
                }
                Intent open = getPackageManager().getLaunchIntentForPackage(getPackageName());
                if (open != null) open.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
                PendingIntent pi = PendingIntent.getActivity(MainActivity.this, 0, open,
                    PendingIntent.FLAG_UPDATE_CURRENT | PendingIntent.FLAG_IMMUTABLE);
                NotificationCompat.Builder b = new NotificationCompat.Builder(MainActivity.this, "exg_main")
                    .setSmallIcon(getApplicationInfo().icon)
                    .setContentTitle(title).setContentText(body)
                    .setAutoCancel(true).setContentIntent(pi);
                nm.notify(nid++, b.build());
            } catch (Exception ignored) { }
        }
    }
}
""".replace("%PKG%", pkg)
open(jp, "w", encoding="utf-8").write(JAVA)
print("MainActivity:", jp)

# ---------- MusicService (фоновое воспроизведение, уведомление плеера) ----------
SERVICE = r"""package %PKG%;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.media.MediaMetadata;
import android.media.session.MediaSession;
import android.media.session.PlaybackState;
import android.os.Build;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.os.SystemClock;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;

/** Фоновая служба плеера EXG Music: уведомление с обложкой и кнопками, экран блокировки, гарнитура/Bluetooth.
 *  Звук играет в WebView (music.js); служба держит процесс живым и пересылает нажатия обратно в JS. */
public class MusicService extends Service {
    static MusicService inst;
    static final String CH = "exg_music";
    static final int NID = 7001;
    static final String A_UPD = "exg.media.upd", A_PP = "exg.media.pp", A_NEXT = "exg.media.next",
        A_PREV = "exg.media.prev", A_STOP = "exg.media.stop";

    private MediaSession session;
    private final Handler h = new Handler(Looper.getMainLooper());
    private String id = "", title = "", artist = "", img = "", artFor = "";
    private boolean playing;
    private long pos, dur;
    private Bitmap art;
    private final Runnable idle = new Runnable() {
        public void run() { finish(); }
    };

    /** Показать/обновить плеер. Если служба уже работает — обновляем напрямую, иначе запускаем. */
    static void show(Context c, String id, String title, String artist, String img, boolean playing, long pos, long dur) {
        MusicService s = inst;
        if (s != null) {
            s.apply(id, title, artist, img, playing, pos, dur);
            return;
        }
        Intent i = new Intent(c, MusicService.class).setAction(A_UPD)
            .putExtra("id", id).putExtra("title", title).putExtra("artist", artist).putExtra("img", img)
            .putExtra("playing", playing).putExtra("pos", pos).putExtra("dur", dur);
        try {
            if (Build.VERSION.SDK_INT >= 26) c.startForegroundService(i); else c.startService(i);
        } catch (Exception ignored) { }
    }

    @Override
    public void onCreate() {
        super.onCreate();
        inst = this;
        if (Build.VERSION.SDK_INT >= 26) {
            NotificationChannel ch = new NotificationChannel(CH, "Плеер EXG Music", NotificationManager.IMPORTANCE_LOW);
            ch.setShowBadge(false);
            ((NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE)).createNotificationChannel(ch);
        }
        session = new MediaSession(this, "EXG Music");
        session.setFlags(MediaSession.FLAG_HANDLES_MEDIA_BUTTONS | MediaSession.FLAG_HANDLES_TRANSPORT_CONTROLS);
        session.setCallback(new MediaSession.Callback() {
            @Override public void onPlay() { MainActivity.toWeb("play"); }
            @Override public void onPause() { MainActivity.toWeb("pause"); }
            @Override public void onSkipToNext() { MainActivity.toWeb("next"); }
            @Override public void onSkipToPrevious() { MainActivity.toWeb("prev"); }
            @Override public void onSeekTo(long p) { MainActivity.toWeb("seek:" + p); }
            @Override public void onStop() { MainActivity.toWeb("stop"); finish(); }
        });
        session.setActive(true);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        String a = intent == null ? null : intent.getAction();
        if (A_UPD.equals(a)) {
            apply(intent.getStringExtra("id"), intent.getStringExtra("title"), intent.getStringExtra("artist"),
                intent.getStringExtra("img"), intent.getBooleanExtra("playing", false),
                intent.getLongExtra("pos", 0), intent.getLongExtra("dur", 0));
        } else if (id.isEmpty() || MainActivity.inst == null) {
            finish();          // уведомление осталось от убитого приложения — просто убираем
        } else if (A_PP.equals(a)) {
            MainActivity.toWeb(playing ? "pause" : "play");
        } else if (A_NEXT.equals(a)) {
            MainActivity.toWeb("next");
        } else if (A_PREV.equals(a)) {
            MainActivity.toWeb("prev");
        } else if (A_STOP.equals(a)) {
            MainActivity.toWeb("stop");
            finish();
        }
        return START_NOT_STICKY;
    }

    void apply(String nid, String t, String a, String im, boolean pl, long p, long d) {
        nid = nid == null ? "" : nid;
        boolean fresh = !nid.equals(id);
        id = nid; title = t == null ? "" : t; artist = a == null ? "" : a; img = im == null ? "" : im;
        playing = pl; pos = p; dur = d;
        if (fresh) {
            art = null;
            artFor = img;
            loadArt(img);
        }
        h.removeCallbacks(idle);
        if (!pl) h.postDelayed(idle, 10 * 60 * 1000L);   // долго на паузе — убираем плеер из шторки
        refresh();
    }

    private void loadArt(final String url) {
        if (url == null || !url.startsWith("http")) return;
        new Thread(new Runnable() {
            public void run() {
                Bitmap b = null;
                try {
                    HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                    c.setConnectTimeout(8000);
                    c.setReadTimeout(8000);
                    InputStream in = c.getInputStream();
                    Bitmap raw = BitmapFactory.decodeStream(in);
                    in.close();
                    if (raw != null) {
                        int m = Math.max(raw.getWidth(), raw.getHeight());
                        b = m > 512 ? Bitmap.createScaledBitmap(raw, raw.getWidth() * 512 / m, raw.getHeight() * 512 / m, true) : raw;
                    }
                } catch (Exception ignored) { }
                final Bitmap fb = b;
                if (fb != null) {
                    h.post(new Runnable() {
                        public void run() {
                            if (inst == MusicService.this && url.equals(artFor)) {
                                art = fb;
                                refresh();
                            }
                        }
                    });
                }
            }
        }).start();
    }

    private PendingIntent act(String action, int code) {
        Intent i = new Intent(this, MusicService.class).setAction(action);
        return PendingIntent.getService(this, code, i,
            PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0));
    }

    private void refresh() {
        if (session == null || id.isEmpty()) return;
        MediaMetadata.Builder mb = new MediaMetadata.Builder()
            .putString(MediaMetadata.METADATA_KEY_TITLE, title)
            .putString(MediaMetadata.METADATA_KEY_ARTIST, artist)
            .putString(MediaMetadata.METADATA_KEY_ALBUM, "EXG Music");
        if (dur > 0) mb.putLong(MediaMetadata.METADATA_KEY_DURATION, dur);
        if (art != null) mb.putBitmap(MediaMetadata.METADATA_KEY_ALBUM_ART, art);
        session.setMetadata(mb.build());
        long actions = PlaybackState.ACTION_PLAY | PlaybackState.ACTION_PAUSE | PlaybackState.ACTION_PLAY_PAUSE
            | PlaybackState.ACTION_SKIP_TO_NEXT | PlaybackState.ACTION_SKIP_TO_PREVIOUS
            | PlaybackState.ACTION_SEEK_TO | PlaybackState.ACTION_STOP;
        session.setPlaybackState(new PlaybackState.Builder().setActions(actions)
            .setState(playing ? PlaybackState.STATE_PLAYING : PlaybackState.STATE_PAUSED, pos, playing ? 1f : 0f,
                SystemClock.elapsedRealtime()).build());

        Notification.Builder b = Build.VERSION.SDK_INT >= 26 ? new Notification.Builder(this, CH) : new Notification.Builder(this);
        b.setSmallIcon(playing ? android.R.drawable.ic_media_play : android.R.drawable.ic_media_pause)
            .setContentTitle(title).setContentText(artist)
            .setDeleteIntent(act(A_STOP, 4)).setOnlyAlertOnce(true).setShowWhen(false)
            .setVisibility(Notification.VISIBILITY_PUBLIC).setOngoing(playing)
            .setCategory(Notification.CATEGORY_TRANSPORT);
        Intent open = getPackageManager().getLaunchIntentForPackage(getPackageName());
        if (open != null) {
            open.addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP);
            b.setContentIntent(PendingIntent.getActivity(this, 0, open,
                PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0)));
        }
        if (art != null) b.setLargeIcon(art);
        b.addAction(android.R.drawable.ic_media_previous, "Назад", act(A_PREV, 1));
        b.addAction(playing ? android.R.drawable.ic_media_pause : android.R.drawable.ic_media_play,
            playing ? "Пауза" : "Играть", act(A_PP, 2));
        b.addAction(android.R.drawable.ic_media_next, "Дальше", act(A_NEXT, 3));
        b.addAction(android.R.drawable.ic_menu_close_clear_cancel, "Закрыть", act(A_STOP, 4));
        b.setStyle(new Notification.MediaStyle().setMediaSession(session.getSessionToken()).setShowActionsInCompactView(0, 1, 2));
        Notification n = b.build();
        if (Build.VERSION.SDK_INT >= 29) startForeground(NID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PLAYBACK);
        else startForeground(NID, n);
    }

    void finish() {
        h.removeCallbacksAndMessages(null);
        id = "";
        try { stopForeground(true); } catch (Exception ignored) { }
        stopSelf();
    }

    @Override
    public void onDestroy() {
        h.removeCallbacksAndMessages(null);
        if (session != null) {
            session.setActive(false);
            session.release();
            session = null;
        }
        if (inst == this) inst = null;
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }
}
"""
sp = os.path.join(os.path.dirname(jp), "MusicService.java")
open(sp, "w", encoding="utf-8").write(SERVICE.replace("%PKG%", pkg))
print("MusicService:", sp)
