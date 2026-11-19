#!/usr/bin/env python3
"""Патчит сгенерированный Capacitor-проект (android/app/src/main):
  1) AndroidManifest.xml — разрешения камера / микрофон / уведомления / вибрация;
  2) MainActivity.java   — мост window.ExgNative: has / request / openSettings / notify / media / mediaStop;
  3) ExgMessagingService / IncomingCallActivity / CallActionReceiver / Push — звонки и уведомления при ЗАКРЫТОМ приложении (FCM);
     плюс правки Gradle (Firebase Messaging) — см. FCM ниже;
  4) MusicService.java   — фоновая служба плеера: уведомление с обложкой и кнопками ◀◀ ▶/❚❚ ▶▶ ✕, экран блокировки, гарнитура.
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
    '<uses-permission android:name="android.permission.USE_FULL_SCREEN_INTENT" />',
    '<uses-permission android:name="android.permission.INTERNET" />',
    '<uses-permission android:name="android.permission.ACCESS_NETWORK_STATE" />',
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
if "ExgMessagingService" not in m:
    comp = """
    <service android:name=".ExgMessagingService" android:exported="false">
        <intent-filter><action android:name="com.google.firebase.MESSAGING_EVENT" /></intent-filter>
    </service>
    <activity android:name=".IncomingCallActivity" android:exported="false" android:launchMode="singleTask"
        android:showWhenLocked="true" android:turnScreenOn="true" android:excludeFromRecents="true" android:taskAffinity=""
        android:theme="@android:style/Theme.DeviceDefault.NoActionBar" />
    <receiver android:name=".CallActionReceiver" android:exported="false" />
"""
    m = m.replace("</application>", comp + "    </application>", 1)
open(mp, "w", encoding="utf-8").write(m)
print("manifest: добавлено", len(add), "строк + служба плеера + FCM-компоненты")

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
import android.net.ConnectivityManager;
import android.net.Network;
import android.net.NetworkCapabilities;
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
import com.google.android.gms.tasks.OnSuccessListener;
import com.google.firebase.messaging.FirebaseMessaging;
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

    static MainActivity inst;
    /** Приложение на экране (между onResume и onPause): тогда звонок и сообщения показывает сам клиент, а не FCM-служба. */
    static volatile boolean visible;
    /** Что надо сделать веб-части после запуска из уведомления: {href, call, act, video}. Забирается через ExgNative.takeLaunch(). */
    private static volatile String launch = "";

    /** FCM-токен -> window.__exgFcm в вебе (он отправит его на сервер). */
    static void toWebToken(final String tok) {
        final MainActivity a = inst;
        if (a == null || tok == null) return;
        a.runOnUiThread(new Runnable() {
            public void run() {
                try {
                    a.getBridge().getWebView().evaluateJavascript(
                        "window.__exgFcm&&window.__exgFcm('" + tok.replaceAll("[^A-Za-z0-9_:.-]", "") + "')", null);
                } catch (Exception ignored) { }
            }
        });
    }

    /** Подтолкнуть веб: появилось действие из уведомления (открыть чат / принять звонок). */
    static void nudge() {
        final MainActivity a = inst;
        if (a == null) return;
        a.runOnUiThread(new Runnable() {
            public void run() {
                try {
                    a.getBridge().getWebView().evaluateJavascript("window.__exgLaunch&&window.__exgLaunch()", null);
                } catch (Exception ignored) { }
            }
        });
    }

    /** Разбор Intent, пришедшего из уведомления или с экрана входящего звонка. */
    private void stash(Intent i) {
        if (i == null) return;
        try {
            String href = i.getStringExtra("exg_href");
            String call = i.getStringExtra("call");
            boolean accept = Push.A_ACCEPT.equals(i.getAction()) && call != null;
            if (accept) Push.dismissCall(this, call);
            if ((href != null && !href.isEmpty()) || accept) {
                JSONObject o = new JSONObject();
                if (href != null && !href.isEmpty()) o.put("href", href);
                if (accept) {
                    o.put("call", call);
                    o.put("act", "accept");
                    o.put("video", i.getBooleanExtra("video", false));
                }
                launch = o.toString();
            }
            i.removeExtra("exg_href");
            i.removeExtra("call");
            i.setAction(Intent.ACTION_MAIN);
        } catch (Exception ignored) { }
    }

    @Override
    public void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        stash(intent);
        nudge();
    }

    @Override
    public void onResume() {
        super.onResume();
        visible = true;
        Push.clearMsgs(this);
        nudge();
    }

    @Override
    public void onPause() {
        visible = false;
        super.onPause();
    }

    /** Команда из уведомления плеера (play/pause/next/prev/seek:N/stop) -> window.__exgMedia в вебе. */
    static void toWeb(final String cmd) {
        final MainActivity a = inst;
        if (a == null) return;
        a.runOnUiThread(new Runnable() {
            public void run() {
                try {
                    String safe = cmd.replace(\"\\\\\", \"\\\\\\\\\").replace(\"'\", \"\\\\'\");
                    a.getBridge().getWebView().evaluateJavascript(
                        \"window.__exgMedia&&window.__exgMedia('\" + safe + \"')\", null);
                } catch (Exception ignored) { }
            }
        });
    }

    @Override
    public void onDestroy() {
        if (inst == this) inst = null;
        super.onDestroy();
    }

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        inst = this;
        Push.channels(this);
        stash(getIntent());
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

        /** Запросить у Firebase токен устройства; он придёт в window.__exgFcm(token). false — Firebase не настроен в этой сборке. */
        @JavascriptInterface
        public boolean fcmInit() {
            try {
                FirebaseMessaging.getInstance().getToken().addOnSuccessListener(new OnSuccessListener<String>() {
                    public void onSuccess(String t) {
                        if (t != null && !t.isEmpty()) {
                            Push.sp(MainActivity.this).edit().putString("fcm", t).apply();
                            toWebToken(t);
                        }
                    }
                });
                return true;
            } catch (Throwable e) {
                return false;
            }
        }

        /** Адрес сервера и токен входа: нужны, чтобы «Отклонить» в уведомлении о звонке работало, не открывая приложение. */
        @JavascriptInterface
        public void setAuth(String base, String token) {
            Push.sp(MainActivity.this).edit().putString("base", base == null ? "" : base)
                .putString("token", token == null ? "" : token).apply();
        }

        /** Действие из уведомления, с которого запустили приложение (JSON или пустая строка). Забирается один раз. */
        @JavascriptInterface
        public String takeLaunch() {
            String s = launch;
            launch = "";
            return s;
        }

        /** Сейчас Wi-Fi/Ethernet без лимита трафика? Нужно автозагрузке музыки («только по Wi-Fi»). */
        @JavascriptInterface
        public boolean isWifi() {
            try {
                ConnectivityManager cm = (ConnectivityManager) getSystemService(Context.CONNECTIVITY_SERVICE);
                Network n = cm.getActiveNetwork();
                if (n == null) return false;
                NetworkCapabilities c = cm.getNetworkCapabilities(n);
                return c != null && (c.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) || c.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET))
                    && !cm.isActiveNetworkMetered();
            } catch (Exception e) {
                return true;
            }
        }

        /** Android 14+: можно ли показывать входящий звонок на весь экран поверх блокировки. */
        @JavascriptInterface
        public boolean fsiOk() {
            if (Build.VERSION.SDK_INT >= 34) {
                return ((NotificationManager) getSystemService(Context.NOTIFICATION_SERVICE)).canUseFullScreenIntent();
            }
            return true;
        }

        @JavascriptInterface
        public void openFsiSettings() {
            runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        Intent i;
                        if (Build.VERSION.SDK_INT >= 34) {
                            i = new Intent(Settings.ACTION_MANAGE_APP_USE_FULL_SCREEN_INTENT, Uri.fromParts("package", getPackageName(), null));
                        } else {
                            i = new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", getPackageName(), null));
                        }
                        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                        startActivity(i);
                    } catch (Exception ignored) { }
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

# ============================================================================ FCM: звонки и уведомления при закрытом приложении
jdir = os.path.dirname(jp)

PUSH = r"""package %PKG%;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.SharedPreferences;
import android.media.AudioAttributes;
import android.media.RingtoneManager;
import android.net.Uri;
import android.os.Build;
import android.service.notification.StatusBarNotification;
import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.app.Person;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.Map;
import org.json.JSONObject;

/** Общие вещи для push: каналы, уведомление «Входящий звонок», обычные уведомления, «Отклонить» без открытия приложения. */
final class Push {
    static final String CH_CALL = "exg_calls_v1", CH_MSG = "exg_msgs_v1";
    static final String A_ACCEPT = "exg.call.accept", A_DECLINE = "exg.call.decline";
    private static final Map<String, ArrayList<String>> HIST = new HashMap<>();

    private Push() { }

    static SharedPreferences sp(Context c) {
        return c.getSharedPreferences("exg_push", Context.MODE_PRIVATE);
    }

    static int idFor(String s) {
        return 10000 + ((s == null ? "" : s).hashCode() & 0xffffff);
    }

    static int flags() {
        return PendingIntent.FLAG_UPDATE_CURRENT | (Build.VERSION.SDK_INT >= 23 ? PendingIntent.FLAG_IMMUTABLE : 0);
    }

    static void channels(Context c) {
        if (Build.VERSION.SDK_INT < 26) return;
        NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
        Uri ring = RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE);
        NotificationChannel call = new NotificationChannel(CH_CALL, "Входящие звонки", NotificationManager.IMPORTANCE_HIGH);
        call.setDescription("Звонок на весь экран с мелодией, даже если приложение закрыто");
        call.setSound(ring, new AudioAttributes.Builder().setUsage(AudioAttributes.USAGE_NOTIFICATION_RINGTONE)
            .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION).build());
        call.enableVibration(true);
        call.setVibrationPattern(new long[]{0, 900, 600, 900, 600, 900});
        call.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        call.setShowBadge(false);
        nm.createNotificationChannel(call);
        NotificationChannel msg = new NotificationChannel(CH_MSG, "Сообщения и уведомления", NotificationManager.IMPORTANCE_HIGH);
        msg.setDescription("Личные сообщения, чаты, комментарии, упоминания, пропущенные звонки");
        msg.enableVibration(true);
        msg.setLockscreenVisibility(Notification.VISIBILITY_PRIVATE);
        nm.createNotificationChannel(msg);
    }

    static PendingIntent open(Context c, String href, String tag) {
        int code = idFor("o" + tag);
        Intent i = new Intent(c, MainActivity.class).setAction("exg.open." + code)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra("exg_href", href == null ? "" : href);
        return PendingIntent.getActivity(c, code, i, flags());
    }

    // ---------- звонок ----------
    static void showCall(Context c, String call, String name, boolean video, String kind, int ringSec) {
        if (call == null || call.isEmpty()) return;
        channels(c);
        if (name == null || name.isEmpty()) name = "Звонок";
        int id = idFor("call" + call);
        Intent full = new Intent(c, IncomingCallActivity.class)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP | Intent.FLAG_ACTIVITY_NO_USER_ACTION)
            .putExtra("call", call).putExtra("name", name).putExtra("video", video).putExtra("ring", ringSec);
        PendingIntent fsi = PendingIntent.getActivity(c, id, full, flags());
        Intent acc = new Intent(c, MainActivity.class).setAction(A_ACCEPT)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
            .putExtra("call", call).putExtra("video", video);
        PendingIntent accPi = PendingIntent.getActivity(c, id + 1, acc, flags());
        Intent dec = new Intent(c, CallActionReceiver.class).setAction(A_DECLINE).putExtra("call", call);
        PendingIntent decPi = PendingIntent.getBroadcast(c, id + 2, dec, flags());
        Person p = new Person.Builder().setName(name).setImportant(true).build();
        NotificationCompat.Builder b = new NotificationCompat.Builder(c, CH_CALL)
            .setSmallIcon(R.drawable.ic_stat_call)
            .setContentTitle(name)
            .setContentText(video ? "Входящий видеозвонок" : "Входящий звонок")
            .setPriority(NotificationCompat.PRIORITY_MAX)
            .setCategory(NotificationCompat.CATEGORY_CALL)
            .setVisibility(NotificationCompat.VISIBILITY_PUBLIC)
            .setOngoing(true).setAutoCancel(false).setOnlyAlertOnce(false)
            .setWhen(System.currentTimeMillis()).setShowWhen(true)
            .setFullScreenIntent(fsi, true)
            .setContentIntent(fsi)
            .setTimeoutAfter(Math.max(10, ringSec) * 1000L)
            .setStyle(NotificationCompat.CallStyle.forIncomingCall(p, decPi, accPi));
        if (Build.VERSION.SDK_INT < 26) {
            b.setSound(RingtoneManager.getDefaultUri(RingtoneManager.TYPE_RINGTONE), android.media.AudioManager.STREAM_RING)
             .setVibrate(new long[]{0, 900, 600, 900, 600, 900});
        }
        Notification n = b.build();
        n.flags |= Notification.FLAG_INSISTENT;       // мелодия повторяется, пока вызов не принят / не отклонён / не истёк
        try {
            ((NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE)).notify(id, n);
        } catch (SecurityException ignored) { }
    }

    /** Убрать вызов (принят, отклонён, отменён звонящим, истёк, принят на другом устройстве). */
    static void dismissCall(Context c, String call) {
        if (call == null) return;
        try {
            NotificationManagerCompat.from(c).cancel(idFor("call" + call));
        } catch (Exception ignored) { }
        IncomingCallActivity.finishFor(call);
    }

    interface Done { void finish(); }

    /** «Отклонить»: сообщаем серверу прямо из фона (адрес и токен входа сохраняет веб-часть: ExgNative.setAuth). */
    static void decline(final Context c, final String call, final Done done) {
        dismissCall(c, call);
        new Thread(new Runnable() {
            public void run() {
                try {
                    SharedPreferences p = sp(c);
                    String base = p.getString("base", ""), tok = p.getString("token", "");
                    if (!base.isEmpty() && !tok.isEmpty()) {
                        HttpURLConnection h = (HttpURLConnection) new URL(base + "/forum/api/calls/decline").openConnection();
                        h.setRequestMethod("POST");
                        h.setConnectTimeout(8000);
                        h.setReadTimeout(8000);
                        h.setDoOutput(true);
                        h.setRequestProperty("Content-Type", "application/json");
                        h.setRequestProperty("Authorization", "Bearer " + tok);
                        OutputStream os = h.getOutputStream();
                        os.write(("{\"call\":" + JSONObject.quote(call) + "}").getBytes("UTF-8"));
                        os.close();
                        h.getResponseCode();
                        h.disconnect();
                    }
                } catch (Exception ignored) {
                } finally {
                    if (done != null) done.finish();
                }
            }
        }).start();
    }

    // ---------- обычные уведомления ----------
    static void showMsg(Context c, String kind, String title, String body, String href, String tag) {
        channels(c);
        if (tag == null || tag.isEmpty()) tag = String.valueOf(System.nanoTime());
        boolean chat = "dm".equals(kind) || "group".equals(kind);
        ArrayList<String> h;
        synchronized (HIST) {
            h = HIST.get(tag);
            if (h == null) {
                h = new ArrayList<>();
                HIST.put(tag, h);
            }
            h.add(body == null ? "" : body);
            while (h.size() > 6) h.remove(0);
            h = new ArrayList<>(h);
        }
        NotificationCompat.Builder b = new NotificationCompat.Builder(c, CH_MSG)
            .setSmallIcon(R.drawable.ic_stat_exg)
            .setColor(0xFF8B6CFF)
            .setContentTitle(title == null || title.isEmpty() ? "KMBP FORUM" : title)
            .setContentText(body)
            .setAutoCancel(true)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setDefaults(NotificationCompat.DEFAULT_ALL)
            .setCategory(chat ? NotificationCompat.CATEGORY_MESSAGE : NotificationCompat.CATEGORY_SOCIAL)
            .setContentIntent(open(c, href, tag));
        if (h.size() > 1) {
            NotificationCompat.InboxStyle st = new NotificationCompat.InboxStyle().setBigContentTitle(title);
            for (String line : h) st.addLine(line);
            b.setStyle(st).setNumber(h.size());
        } else {
            b.setStyle(new NotificationCompat.BigTextStyle().bigText(body));
        }
        try {
            NotificationManagerCompat.from(c).notify(idFor("m" + tag), b.build());
        } catch (SecurityException ignored) { }
    }

    /** Приложение открыли — старые уведомления о сообщениях больше не нужны (как в Telegram). */
    static void clearMsgs(Context c) {
        synchronized (HIST) { HIST.clear(); }
        if (Build.VERSION.SDK_INT < 26) return;
        try {
            NotificationManager nm = (NotificationManager) c.getSystemService(Context.NOTIFICATION_SERVICE);
            for (StatusBarNotification s : nm.getActiveNotifications()) {
                if (CH_MSG.equals(s.getNotification().getChannelId())) nm.cancel(s.getId());
            }
        } catch (Exception ignored) { }
    }
}
"""

SERVICE_FCM = r"""package %PKG%;

import androidx.core.app.NotificationManagerCompat;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;
import java.util.Map;

/** Принимает push от сервера форума (data-сообщения, высокий приоритет) — работает и когда приложение закрыто. */
public class ExgMessagingService extends FirebaseMessagingService {
    @Override
    public void onNewToken(String token) {
        Push.sp(this).edit().putString("fcm", token).apply();
        MainActivity.toWebToken(token);        // если приложение живо — веб сам отправит токен на сервер; иначе отправит при следующем запуске
    }

    @Override
    public void onMessageReceived(RemoteMessage m) {
        Map<String, String> d = m.getData();
        String type = d.get("type");
        if (type == null) return;
        try {
            if ("call_end".equals(type)) {
                Push.dismissCall(this, d.get("call"));
                return;
            }
            if (!NotificationManagerCompat.from(this).areNotificationsEnabled()) return;
            // Приложение открыто — звонок и баннеры покажет сам клиент (там и звук, и карточка «Принять / Отклонить»)
            if (MainActivity.visible) return;
            if ("call".equals(type)) {
                int ring = 45;
                try { ring = Integer.parseInt(d.get("ring")); } catch (Exception ignored) { }
                Push.showCall(this, d.get("call"), d.get("name"), "1".equals(d.get("video")), d.get("kind"), ring);
            } else if ("msg".equals(type)) {
                Push.showMsg(this, d.get("kind"), d.get("title"), d.get("body"), d.get("href"), d.get("tag"));
            }
        } catch (Exception ignored) { }
    }
}
"""

CALL_ACTIVITY = r"""package %PKG%;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.graphics.Color;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Экран входящего звонка: поверх блокировки, включает экран. «Принять» открывает приложение и сразу входит в звонок. */
public class IncomingCallActivity extends Activity {
    static IncomingCallActivity cur;
    private String call = "";
    private boolean video;
    private final Handler h = new Handler(Looper.getMainLooper());

    static void finishFor(final String call) {
        final IncomingCallActivity a = cur;
        if (a == null) return;
        if (call != null && !call.equals(a.call)) return;
        a.runOnUiThread(new Runnable() {
            public void run() { a.finish(); }
        });
    }

    private int dp(int v) {
        return Math.round(v * getResources().getDisplayMetrics().density);
    }

    private GradientDrawable oval(int color) {
        GradientDrawable g = new GradientDrawable();
        g.setShape(GradientDrawable.OVAL);
        g.setColor(color);
        return g;
    }

    private TextView text(String t, int size, int color, boolean bold) {
        TextView v = new TextView(this);
        v.setText(t);
        v.setTextSize(size);
        v.setTextColor(color);
        v.setGravity(Gravity.CENTER);
        if (bold) v.setTypeface(Typeface.DEFAULT_BOLD);
        return v;
    }

    private LinearLayout action(String icon, String label, int color, View.OnClickListener l) {
        LinearLayout col = new LinearLayout(this);
        col.setOrientation(LinearLayout.VERTICAL);
        col.setGravity(Gravity.CENTER_HORIZONTAL);
        TextView b = text(icon, 30, Color.WHITE, true);
        b.setBackground(oval(color));
        b.setOnClickListener(l);
        col.addView(b, new LinearLayout.LayoutParams(dp(76), dp(76)));
        TextView t = text(label, 14, 0xFFCFCBE6, false);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(-2, -2);
        lp.topMargin = dp(10);
        col.addView(t, lp);
        return col;
    }

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);
        cur = this;
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
        } else {
            getWindow().addFlags(WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON);
        }
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        Intent in = getIntent();
        call = in.getStringExtra("call") == null ? "" : in.getStringExtra("call");
        video = in.getBooleanExtra("video", false);
        String name = in.getStringExtra("name") == null ? "Звонок" : in.getStringExtra("name");
        int ring = in.getIntExtra("ring", 45);

        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setGravity(Gravity.CENTER_HORIZONTAL);
        root.setBackgroundColor(0xFF050409);
        root.setPadding(dp(24), dp(90), dp(24), dp(70));

        root.addView(text("KMBP FORUM · " + (video ? "видеозвонок" : "звонок"), 14, 0xFFA8A3C0, false));
        String ini = name.trim().isEmpty() ? "?" : name.trim().substring(0, 1).toUpperCase();
        TextView av = text(ini, 48, Color.WHITE, true);
        av.setBackground(oval(0xFF6C4DFF));
        LinearLayout.LayoutParams ap = new LinearLayout.LayoutParams(dp(130), dp(130));
        ap.topMargin = dp(40);
        root.addView(av, ap);
        TextView nm = text(name, 28, Color.WHITE, true);
        LinearLayout.LayoutParams np = new LinearLayout.LayoutParams(-1, -2);
        np.topMargin = dp(28);
        root.addView(nm, np);
        TextView st = text(video ? "Входящий видеозвонок…" : "Входящий звонок…", 16, 0xFFA8A3C0, false);
        LinearLayout.LayoutParams sp = new LinearLayout.LayoutParams(-1, -2);
        sp.topMargin = dp(8);
        root.addView(st, sp);
        root.addView(new View(this), new LinearLayout.LayoutParams(1, 0, 1f));

        LinearLayout row = new LinearLayout(this);
        row.setOrientation(LinearLayout.HORIZONTAL);
        row.setGravity(Gravity.CENTER);
        row.addView(action("✕", "Отклонить", 0xFFE5484D, new View.OnClickListener() {
            public void onClick(View v) { decline(); }
        }), new LinearLayout.LayoutParams(0, -2, 1f));
        row.addView(action(video ? "📹" : "📞", "Принять", 0xFF2FB863, new View.OnClickListener() {
            public void onClick(View v) { accept(); }
        }), new LinearLayout.LayoutParams(0, -2, 1f));
        root.addView(row, new LinearLayout.LayoutParams(-1, -2));
        setContentView(root);

        h.postDelayed(new Runnable() {
            public void run() { finish(); }
        }, Math.max(10, ring) * 1000L);
    }

    private void decline() {
        Push.decline(getApplicationContext(), call, null);
        finish();
    }

    private void accept() {
        final Runnable go = new Runnable() {
            public void run() {
                Intent i = new Intent(IncomingCallActivity.this, MainActivity.class).setAction(Push.A_ACCEPT)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP | Intent.FLAG_ACTIVITY_CLEAR_TOP)
                    .putExtra("call", call).putExtra("video", video);
                startActivity(i);
                Push.dismissCall(getApplicationContext(), call);
                finish();
            }
        };
        KeyguardManager km = (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && km != null && km.isKeyguardLocked()) {
            km.requestDismissKeyguard(this, new KeyguardManager.KeyguardDismissCallback() {
                @Override public void onDismissSucceeded() { go.run(); }
                @Override public void onDismissError() { go.run(); }
            });
        } else {
            go.run();
        }
    }

    @Override
    public void onBackPressed() { }

    @Override
    protected void onDestroy() {
        h.removeCallbacksAndMessages(null);
        if (cur == this) cur = null;
        super.onDestroy();
    }
}
"""

RECEIVER = r"""package %PKG%;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** Кнопка «Отклонить» в уведомлении о звонке. */
public class CallActionReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context c, Intent i) {
        final String call = i.getStringExtra("call");
        if (call == null) return;
        final PendingResult pr = goAsync();
        Push.decline(c.getApplicationContext(), call, new Push.Done() {
            public void finish() { pr.finish(); }
        });
    }
}
"""

ICON_EXG = """<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" android:height="24dp"
    android:viewportWidth="24" android:viewportHeight="24">
    <path android:fillColor="#FFFFFFFF" android:pathData="M20,2H4C2.9,2 2,2.9 2,4v18l4,-4h14c1.1,0 2,-0.9 2,-2V4C22,2.9 21.1,2 20,2z"/>
</vector>
"""
ICON_CALL = """<vector xmlns:android="http://schemas.android.com/apk/res/android" android:width="24dp" android:height="24dp"
    android:viewportWidth="24" android:viewportHeight="24">
    <path android:fillColor="#FFFFFFFF" android:pathData="M6.62,10.79c1.44,2.83 3.76,5.14 6.59,6.59l2.2,-2.2c0.27,-0.27 0.67,-0.36 1.02,-0.24 1.12,0.37 2.33,0.57 3.57,0.57 0.55,0 1,0.45 1,1V20c0,0.55 -0.45,1 -1,1 -9.39,0 -17,-7.61 -17,-17 0,-0.55 0.45,-1 1,-1h3.5c0.55,0 1,0.45 1,1 0,1.25 0.2,2.45 0.57,3.57 0.11,0.35 0.03,0.74 -0.25,1.02l-2.2,2.2z"/>
</vector>
"""

for name, src in (("Push.java", PUSH), ("ExgMessagingService.java", SERVICE_FCM), ("IncomingCallActivity.java", CALL_ACTIVITY),
                  ("CallActionReceiver.java", RECEIVER)):
    open(os.path.join(jdir, name), "w", encoding="utf-8").write(src.replace("%PKG%", pkg))
    print("FCM:", name)
dr = os.path.join(main, "res", "drawable")
os.makedirs(dr, exist_ok=True)
open(os.path.join(dr, "ic_stat_exg.xml"), "w", encoding="utf-8").write(ICON_EXG)
open(os.path.join(dr, "ic_stat_call.xml"), "w", encoding="utf-8").write(ICON_CALL)

# ---------- Gradle: Firebase Messaging + плагин google-services ----------
android_dir = os.path.normpath(os.path.join(main, "..", "..", ".."))
app_dir = os.path.normpath(os.path.join(main, "..", ".."))
rg = os.path.join(android_dir, "build.gradle")
ag = os.path.join(app_dir, "build.gradle")
if os.path.exists(rg):
    g = open(rg, encoding="utf-8").read()
    if "com.google.gms:google-services" not in g:
        g, n = re.subn(r"(classpath\s+['\"]com\.android\.tools\.build:gradle:[^'\"]+['\"])",
                       r"\1\n        classpath 'com.google.gms:google-services:4.4.2'", g, count=1)
        print("gradle(root): google-services classpath", "добавлен" if n else "НЕ добавлен — добавьте вручную")
        open(rg, "w", encoding="utf-8").write(g)
if os.path.exists(ag):
    g = open(ag, encoding="utf-8").read()
    if "firebase-messaging" not in g:
        g, n = re.subn(r"(\ndependencies\s*\{)", r"\1\n    implementation 'com.google.firebase:firebase-messaging:24.0.0'", g, count=1)
        print("gradle(app): firebase-messaging", "добавлен" if n else "НЕ добавлен — добавьте вручную")
    if "com.google.gms.google-services" not in g:
        g += """
try {
    def servicesJSON = file('google-services.json')
    if (servicesJSON.text) {
        apply plugin: 'com.google.gms.google-services'
    }
} catch(Exception e) {
    logger.info("google-services.json not found, google-services plugin not applied")
}
"""
    open(ag, "w", encoding="utf-8").write(g)
if not os.path.exists(os.path.join(app_dir, "google-services.json")):
    print("ВНИМАНИЕ: нет android/app/google-services.json — APK соберётся, но push при закрытом приложении работать не будут "
          "(положите файл из Firebase Console или секрет GOOGLE_SERVICES_JSON в GitHub)")
