package io.github.androidagent

import android.content.Context
import java.security.SecureRandom
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Small shared state: the private key, the pause switch and a visible log of actions. */
object Agent {
    const val PORT = 7912
    private const val PREFS = "agent"
    private val log = ArrayDeque<String>()
    var listener: (() -> Unit)? = null

    fun key(ctx: Context): String {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return p.getString("key", null) ?: newKey(ctx)
    }

    fun newKey(ctx: Context): String {
        val alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
        val rnd = SecureRandom()
        val k = (1..24).map { alphabet[rnd.nextInt(alphabet.length)] }.joinToString("")
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString("key", k).apply()
        return k
    }

    fun allowed(ctx: Context) =
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("allowed", true)

    fun setAllowed(ctx: Context, on: Boolean) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("allowed", on).apply()
        record(ctx.getString(if (on) R.string.log_allowed else R.string.log_paused))
    }

    @Synchronized
    fun record(what: String) {
        val t = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date())
        log.addFirst("$t  $what")
        while (log.size > 30) log.removeLast()
        listener?.invoke()
    }

    @Synchronized
    fun recent(): List<String> = log.toList()
}
