package io.github.androidagent

import android.accessibilityservice.AccessibilityService
import android.accessibilityservice.GestureDescription
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.graphics.Path
import android.graphics.Rect
import android.os.Build
import android.view.WindowManager
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import org.json.JSONObject
import java.io.BufferedReader
import java.io.InputStreamReader
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

/**
 * Accessibility service + a tiny HTTP server on 127.0.0.1:7912.
 * Every request must carry the private key (header X-Key). Endpoints:
 *   GET  /ping               {"ok":true,...}
 *   GET  /screen             uiautomator-style XML of the active window (same format as `uiautomator dump`)
 *   POST /tap   {"x","y","long"}       POST /swipe {"x1","y1","x2","y2","ms"}
 *   POST /type  {"text"}                POST /key   {"key": back|home|recents|notifications|enter}
 */
class AgentService : AccessibilityService() {

    @Volatile private var server: ServerSocket? = null

    override fun onServiceConnected() {
        running = true
        Agent.record(getString(R.string.log_started))
        showNotification()
        thread(name = "agent-server", isDaemon = true) { serve() }
    }

    override fun onDestroy() {
        running = false
        try { server?.close() } catch (_: Exception) {}
        getSystemService(NotificationManager::class.java).cancel(NOTIF_ID)
        Agent.record(getString(R.string.log_stopped))
        super.onDestroy()
    }

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {}
    override fun onInterrupt() {}

    // ---------- server ----------
    private fun serve() {
        try {
            server = ServerSocket(Agent.PORT, 8, InetAddress.getByName("127.0.0.1"))
            while (running) {
                val s = server?.accept() ?: break
                thread(isDaemon = true) { handle(s) }
            }
        } catch (_: Exception) {
        }
    }

    private fun handle(sock: Socket) { sock.use { s ->
        s.soTimeout = 15000
        val input = BufferedReader(InputStreamReader(s.getInputStream(), Charsets.UTF_8))
        val requestLine = input.readLine() ?: return
        val parts = requestLine.split(" ")
        if (parts.size < 2) return
        val method = parts[0]
        val path = parts[1].substringBefore("?")
        val headers = HashMap<String, String>()
        while (true) {
            val l = input.readLine() ?: break
            if (l.isEmpty()) break
            val i = l.indexOf(':')
            if (i > 0) headers[l.substring(0, i).trim().lowercase()] = l.substring(i + 1).trim()
        }
        val len = headers["content-length"]?.toIntOrNull() ?: 0
        val body = if (len > 0) CharArray(len).also { var r = 0; while (r < len) { val n = input.read(it, r, len - r); if (n < 0) break; r += n } }.concatToString() else ""

        val (code, type, out) = route(method, path, headers["x-key"] ?: "", body)
        val bytes = out.toByteArray(Charsets.UTF_8)
        s.getOutputStream().apply {
            write("HTTP/1.1 $code\r\nContent-Type: $type; charset=utf-8\r\nContent-Length: ${bytes.size}\r\nConnection: close\r\n\r\n".toByteArray())
            write(bytes)
            flush()
        }
    } }

    private fun json(vararg kv: Pair<String, Any?>) = Triple("200 OK", "application/json", JSONObject(mapOf(*kv)).toString())
    private fun fail(code: String, msg: String) = Triple(code, "application/json", JSONObject(mapOf("ok" to false, "error" to msg)).toString())

    private fun route(method: String, path: String, key: String, body: String): Triple<String, String, String> {
        if (!sameKey(key, Agent.key(this))) return fail("401 Unauthorized", "missing or wrong key")
        if (path == "/ping") return json("ok" to true, "version" to "0.4.0", "allowed" to Agent.allowed(this))
        if (!Agent.allowed(this)) return fail("423 Locked", "paused by the user in the android-agent app")
        val a = if (body.isNotBlank()) JSONObject(body) else JSONObject()
        return try {
            when ("$method $path") {
                "GET /screen" -> Triple("200 OK", "text/xml", dumpXml())
                "POST /tap" -> {
                    val x = a.getInt("x"); val y = a.getInt("y"); val long = a.optBoolean("long")
                    Agent.record(getString(if (long) R.string.log_longpress else R.string.log_tap, x, y))
                    json("ok" to gesture(x, y, x, y, if (long) 700 else 60))
                }
                "POST /swipe" -> {
                    Agent.record(getString(R.string.log_swipe))
                    json("ok" to gesture(a.getInt("x1"), a.getInt("y1"), a.getInt("x2"), a.getInt("y2"), a.optInt("ms", 300)))
                }
                "POST /type" -> typeText(a.getString("text"))
                "POST /key" -> pressKey(a.getString("key"))
                else -> fail("404 Not Found", "unknown endpoint $method $path")
            }
        } catch (e: Exception) {
            fail("400 Bad Request", e.message ?: "error")
        }
    }

    private fun sameKey(a: String, b: String) =
        MessageDigest.isEqual(a.toByteArray(), b.toByteArray())

    // ---------- reading ----------
    private fun dumpXml(): String {
        val root = rootInActiveWindow ?: return "<?xml version='1.0' encoding='UTF-8' standalone='yes' ?><hierarchy rotation=\"0\"/>"
        val sb = StringBuilder("<?xml version='1.0' encoding='UTF-8' standalone='yes' ?>")
        sb.append("<hierarchy rotation=\"").append(rotation()).append("\">")
        appendNode(sb, root, 0)
        sb.append("</hierarchy>")
        Agent.record(getString(R.string.log_read, root.packageName))
        return sb.toString()
    }

    private fun appendNode(sb: StringBuilder, n: AccessibilityNodeInfo, depth: Int) {
        if (depth > 60) return
        val r = Rect(); n.getBoundsInScreen(r)
        val text = if (n.isPassword) "" else (n.text?.toString() ?: "")
        sb.append("<node class=\"").append(esc(n.className)).append("\" package=\"").append(esc(n.packageName))
            .append("\" text=\"").append(esc(text)).append("\" content-desc=\"").append(esc(n.contentDescription))
            .append("\" resource-id=\"").append(esc(n.viewIdResourceName))
            .append("\" clickable=\"").append(n.isClickable).append("\" long-clickable=\"").append(n.isLongClickable)
            .append("\" scrollable=\"").append(n.isScrollable).append("\" checkable=\"").append(n.isCheckable)
            .append("\" checked=\"").append(n.isChecked).append("\" focused=\"").append(n.isFocused)
            .append("\" enabled=\"").append(n.isEnabled).append("\" password=\"").append(n.isPassword)
            .append("\" bounds=\"[").append(r.left).append(',').append(r.top).append("][")
            .append(r.right).append(',').append(r.bottom).append("]\">")
        for (i in 0 until n.childCount) {
            val c = n.getChild(i) ?: continue
            appendNode(sb, c, depth + 1)
        }
        sb.append("</node>")
    }

    private fun esc(s: CharSequence?): String {
        if (s == null) return ""
        val b = StringBuilder(s.length)
        for (ch in s) when (ch) {
            '&' -> b.append("&amp;"); '<' -> b.append("&lt;"); '>' -> b.append("&gt;")
            '"' -> b.append("&quot;"); '\n' -> b.append("&#10;")
            else -> if (ch >= ' ' || ch == '\t') b.append(ch)
        }
        return b.toString()
    }

    @Suppress("DEPRECATION")
    private fun rotation(): Int = getSystemService(WindowManager::class.java).defaultDisplay.rotation

    // ---------- acting ----------
    private fun gesture(x1: Int, y1: Int, x2: Int, y2: Int, ms: Int): Boolean {
        val path = Path().apply { moveTo(x1.toFloat(), y1.toFloat()); lineTo(x2.toFloat(), y2.toFloat()) }
        val g = GestureDescription.Builder()
            .addStroke(GestureDescription.StrokeDescription(path, 0, ms.toLong().coerceAtLeast(1)))
            .build()
        val done = CountDownLatch(1)
        var ok = false
        dispatchGesture(g, object : GestureResultCallback() {
            override fun onCompleted(d: GestureDescription?) { ok = true; done.countDown() }
            override fun onCancelled(d: GestureDescription?) { done.countDown() }
        }, null)
        done.await(ms + 3000L, TimeUnit.MILLISECONDS)
        return ok
    }

    private fun typeText(text: String): Triple<String, String, String> {
        val node = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
            ?: return fail("409 Conflict", "no focused text field: tap the field first")
        val current = if (Build.VERSION.SDK_INT >= 26 && node.isShowingHintText) "" else (node.text?.toString() ?: "")
        val args = android.os.Bundle().apply {
            putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, current + text)
        }
        val ok = node.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args)
        Agent.record(getString(R.string.log_typed, text.length))
        return json("ok" to ok)
    }

    private fun pressKey(key: String): Triple<String, String, String> {
        val action = when (key) {
            "back" -> GLOBAL_ACTION_BACK
            "home" -> GLOBAL_ACTION_HOME
            "recents" -> GLOBAL_ACTION_RECENTS
            "notifications" -> GLOBAL_ACTION_NOTIFICATIONS
            "enter" -> {
                val node = rootInActiveWindow?.findFocus(AccessibilityNodeInfo.FOCUS_INPUT)
                val ok = Build.VERSION.SDK_INT >= 30 && node != null &&
                    node.performAction(AccessibilityNodeInfo.AccessibilityAction.ACTION_IME_ENTER.id)
                Agent.record(getString(R.string.log_key, "Enter"))
                return json("ok" to ok)
            }
            else -> return fail("400 Bad Request", "unknown key $key")
        }
        Agent.record(getString(R.string.log_key, key.replaceFirstChar { it.uppercase() }))
        return json("ok" to performGlobalAction(action))
    }

    // ---------- visible presence ----------
    private fun showNotification() {
        val nm = getSystemService(NotificationManager::class.java)
        nm.createNotificationChannel(NotificationChannel(CHANNEL, getString(R.string.notif_channel), NotificationManager.IMPORTANCE_LOW))
        val open = PendingIntent.getActivity(this, 0, Intent(this, MainActivity::class.java), PendingIntent.FLAG_IMMUTABLE)
        val n = Notification.Builder(this, CHANNEL)
            .setSmallIcon(android.R.drawable.ic_menu_view)
            .setContentTitle(getString(R.string.app_name))
            .setContentText(getString(R.string.notif_text))
            .setContentIntent(open)
            .setOngoing(true)
            .build()
        try { nm.notify(NOTIF_ID, n) } catch (_: SecurityException) {}
    }

    companion object {
        @Volatile var running = false
        private const val CHANNEL = "activity"
        private const val NOTIF_ID = 1

        fun isEnabled(ctx: Context): Boolean {
            val list = android.provider.Settings.Secure.getString(
                ctx.contentResolver, android.provider.Settings.Secure.ENABLED_ACCESSIBILITY_SERVICES) ?: return false
            return list.split(':').any { it.endsWith("/.AgentService") && it.startsWith(ctx.packageName) ||
                it == "${ctx.packageName}/${AgentService::class.java.name}" }
        }
    }
}
