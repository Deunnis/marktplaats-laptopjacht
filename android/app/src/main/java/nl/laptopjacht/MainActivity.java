package nl.laptopjacht;

import android.app.Activity;
import android.os.Build;
import android.os.Bundle;
import android.util.Log;
import android.view.View;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import java.io.BufferedReader;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.zip.GZIPInputStream;

/**
 * Laptopjacht - a WebView shell around the deal browser.
 *
 * The listing data is fetched natively (not from JavaScript) so that no CORS
 * policy applies, and cached on disk so the app opens instantly offline.
 */
public class MainActivity extends Activity {

    private static final String TAG = "Laptopjacht";
    private static final String DATA_URL =
        "https://raw.githubusercontent.com/Deunnis/marktplaats-laptopjacht/data/listings.json";
    private static final String CACHE_FILE = "listings.json";
    /** Auto-refresh on open if the cache is older than this. */
    private static final long STALE_MS = 30L * 60L * 1000L;

    private WebView web;
    private final ExecutorService pool = Executors.newSingleThreadExecutor();
    private volatile boolean fetching = false;

    @Override
    protected void onCreate(Bundle saved) {
        super.onCreate(saved);

        web = new WebView(this);
        setContentView(web);

        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(true);
        s.setCacheMode(WebSettings.LOAD_DEFAULT);

        // Let the page's prefers-color-scheme follow the system theme where supported.
        if (Build.VERSION.SDK_INT >= 33) {
            try { s.setAlgorithmicDarkeningAllowed(true); } catch (Throwable ignored) {}
        }

        web.addJavascriptInterface(new Bridge(), "Android");
        web.setWebViewClient(new WebViewClient() {
            @Override public void onPageFinished(WebView v, String url) {
                // Refresh on every open when the cached copy is stale.
                if (cacheAgeMs() > STALE_MS) fetchData(false);
            }
        });
        web.loadUrl("file:///android_asset/index.html");
    }

    // ------------------------------------------------------------ JS bridge

    private class Bridge {
        /** Cached listing JSON, or "" when nothing has been downloaded yet. */
        @JavascriptInterface public String getData() { return readCache(); }

        /** Milliseconds since the cache was written; -1 when there is no cache. */
        @JavascriptInterface public long cacheAge() { return cacheAgeMs(); }

        @JavascriptInterface public boolean isFetching() { return fetching; }

        /** Called by the in-page Refresh button and by pull-to-refresh. */
        @JavascriptInterface public void refresh() { fetchData(true); }
    }

    // ------------------------------------------------------------ networking

    private File cacheFile() { return new File(getFilesDir(), CACHE_FILE); }

    private long cacheAgeMs() {
        File f = cacheFile();
        if (!f.exists() || f.length() == 0) return -1;
        return System.currentTimeMillis() - f.lastModified();
    }

    private String readCache() {
        File f = cacheFile();
        if (!f.exists() || f.length() == 0) return "";
        try (FileInputStream in = new FileInputStream(f);
             ByteArrayOutputStream bo = new ByteArrayOutputStream()) {
            byte[] buf = new byte[16384];
            int n;
            while ((n = in.read(buf)) > 0) bo.write(buf, 0, n);
            return bo.toString("UTF-8");
        } catch (Exception e) {
            Log.w(TAG, "cache read failed", e);
            return "";
        }
    }

    private void fetchData(final boolean userInitiated) {
        if (fetching) return;
        fetching = true;
        notifyJs("__lpjStatus", "'fetching'");

        pool.execute(() -> {
            String err = null;
            try {
                HttpURLConnection c = (HttpURLConnection) new URL(DATA_URL).openConnection();
                c.setRequestProperty("Accept-Encoding", "gzip");
                c.setRequestProperty("User-Agent", "Laptopjacht-Android");
                c.setConnectTimeout(15000);
                c.setReadTimeout(45000);

                int code = c.getResponseCode();
                if (code != 200) throw new Exception("HTTP " + code);

                InputStream in = c.getInputStream();
                if ("gzip".equalsIgnoreCase(c.getContentEncoding())) in = new GZIPInputStream(in);

                StringBuilder sb = new StringBuilder();
                try (BufferedReader r = new BufferedReader(new InputStreamReader(in, "UTF-8"))) {
                    char[] buf = new char[16384];
                    int n;
                    while ((n = r.read(buf)) > 0) sb.append(buf, 0, n);
                }
                String body = sb.toString();
                if (body.length() < 100 || !body.trim().startsWith("{"))
                    throw new Exception("unexpected payload");

                // Only replace the cache once the download is known-good.
                File tmp = new File(getFilesDir(), CACHE_FILE + ".tmp");
                try (FileOutputStream out = new FileOutputStream(tmp)) {
                    out.write(body.getBytes("UTF-8"));
                }
                if (!tmp.renameTo(cacheFile())) {
                    tmp.delete();
                    throw new Exception("could not save");
                }
            } catch (Exception e) {
                Log.w(TAG, "fetch failed", e);
                err = e.getMessage() == null ? "network error" : e.getMessage();
            }

            final String fErr = err;
            runOnUiThread(() -> {
                fetching = false;
                if (fErr == null) notifyJs("__lpjData", "null");
                else notifyJs("__lpjError", "'" + fErr.replace("'", "") + "'");
            });
        });
    }

    private void notifyJs(String fn, String arg) {
        if (web == null) return;
        web.evaluateJavascript("if(window." + fn + ")window." + fn + "(" + arg + ")", null);
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override protected void onDestroy() {
        pool.shutdownNow();
        super.onDestroy();
    }
}
