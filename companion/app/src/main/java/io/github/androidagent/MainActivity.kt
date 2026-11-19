package io.github.androidagent

import android.Manifest
import android.app.Activity
import android.content.ClipData
import android.content.ClipboardManager
import android.content.Intent
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.TextUtils
import android.view.Gravity
import android.view.View
import android.view.ViewGroup.LayoutParams.MATCH_PARENT
import android.view.ViewGroup.LayoutParams.WRAP_CONTENT
import android.widget.Button
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.Switch
import android.widget.TextView
import android.widget.Toast

/** One scrolling screen, drawn in code (no libraries): status, setup steps, key, privacy, activity. */
class MainActivity : Activity() {

    private val bg = Color.parseColor("#0E0F13")
    private val card = Color.parseColor("#181A21")
    private val line = Color.parseColor("#262934")
    private val text1 = Color.parseColor("#F2F3F7")
    private val text2 = Color.parseColor("#9AA0AE")
    private val violet = Color.parseColor("#6D5DFC")
    private val teal = Color.parseColor("#00C2A8")
    private val green = Color.parseColor("#19C37D")
    private val amber = Color.parseColor("#F5A524")
    private val grey = Color.parseColor("#5B6170")

    private lateinit var root: LinearLayout
    private lateinit var statusDot: View
    private lateinit var statusTitle: TextView
    private lateinit var statusSub: TextView
    private lateinit var accessSwitch: Switch
    private lateinit var keyView: TextView
    private lateinit var activityBox: LinearLayout
    private val steps = mutableListOf<Pair<TextView, () -> Boolean>>()

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        window.statusBarColor = bg
        window.navigationBarColor = bg
        if (Build.VERSION.SDK_INT >= 33) requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 1)

        root = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL; setPadding(dp(18), dp(18), dp(18), dp(28)) }
        setContentView(ScrollView(this).apply { setBackgroundColor(bg); addView(root) })

        header()
        statusCard()
        section(getString(R.string.setup_title))
        if (Build.VERSION.SDK_INT >= 33) step(1, R.string.step1_title, R.string.step1_text, R.string.step1_button, {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:$packageName")))
        }) { AgentService.isEnabled(this) }
        step(if (Build.VERSION.SDK_INT >= 33) 2 else 1, R.string.step2_title, R.string.step2_text, R.string.step2_button, {
            startActivity(Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS))
        }) { AgentService.isEnabled(this) }
        step(if (Build.VERSION.SDK_INT >= 33) 3 else 2, R.string.step3_title, R.string.step3_text, R.string.step3_button, {
            try {
                startActivity(Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName")))
            } catch (_: Exception) {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            }
        }) { getSystemService(PowerManager::class.java).isIgnoringBatteryOptimizations(packageName) }
        keyCard(if (Build.VERSION.SDK_INT >= 33) 4 else 3)
        privacyCard()
        activityCard()
    }

    override fun onResume() {
        super.onResume()
        Agent.listener = { runOnUiThread { refresh() } }
        refresh()
    }

    override fun onPause() {
        Agent.listener = null
        super.onPause()
    }

    // ---------- sections ----------
    private fun header() {
        val box = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(26), dp(22), dp(24))
            background = GradientDrawable(GradientDrawable.Orientation.TL_BR, intArrayOf(violet, teal)).apply { cornerRadius = dp(26).toFloat() }
        }
        box.addView(label("✦  android-agent", 26f, Color.WHITE, bold = true))
        box.addView(label(getString(R.string.tagline), 15f, Color.parseColor("#E9ECFF")).apply { setPadding(0, dp(6), 0, 0) })
        root.addView(box, lp(bottom = 14))
    }

    private fun statusCard() {
        val c = cardBox()
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        statusDot = View(this).apply { background = circle(grey) }
        row.addView(statusDot, LinearLayout.LayoutParams(dp(14), dp(14)).apply { rightMargin = dp(12) })
        statusTitle = label("", 22f, text1, bold = true)
        row.addView(statusTitle)
        c.addView(row)
        statusSub = label("", 14f, text2).apply { setPadding(0, dp(8), 0, dp(14)) }
        c.addView(statusSub)
        c.addView(divider())
        accessSwitch = Switch(this).apply {
            text = getString(R.string.agent_access)
            setTextColor(text1); textSize = 16f
            setPadding(0, dp(12), 0, 0)
            setOnCheckedChangeListener { _, on -> if (on != Agent.allowed(context)) { Agent.setAllowed(context, on); refresh() } }
        }
        c.addView(accessSwitch)
        root.addView(c, lp(bottom = 22))
    }

    private fun step(n: Int, title: Int, body: Int, button: Int, onClick: () -> Unit, done: () -> Boolean) {
        val c = cardBox()
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        val badge = label("$n", 15f, Color.WHITE, bold = true).apply { gravity = Gravity.CENTER }
        row.addView(badge, LinearLayout.LayoutParams(dp(30), dp(30)).apply { rightMargin = dp(12) })
        row.addView(label(getString(title), 17f, text1, bold = true))
        c.addView(row)
        c.addView(label(getString(body), 14f, text2).apply { setPadding(dp(42), dp(6), 0, dp(12)) })
        val b = pillButton(getString(button), filled = true) { onClick() }
        c.addView(b, LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply { leftMargin = dp(42) })
        steps += badge to done
        root.addView(c, lp(bottom = 12))
    }

    private fun keyCard(n: Int) {
        val c = cardBox()
        val row = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        row.addView(label("$n", 15f, Color.WHITE, bold = true).apply { gravity = Gravity.CENTER; background = circle(violet) },
            LinearLayout.LayoutParams(dp(30), dp(30)).apply { rightMargin = dp(12) })
        row.addView(label(getString(R.string.step4_title), 17f, text1, bold = true))
        c.addView(row)
        c.addView(label(getString(R.string.step4_text), 14f, text2).apply { setPadding(dp(42), dp(6), 0, dp(12)) })
        keyView = label("", 18f, text1).apply {
            typeface = Typeface.MONOSPACE; letterSpacing = 0.06f
            setPadding(dp(16), dp(14), dp(16), dp(14))
            background = GradientDrawable().apply { cornerRadius = dp(14).toFloat(); setColor(Color.parseColor("#11131A")); setStroke(dp(1), line) }
            setTextIsSelectable(true)
        }
        c.addView(keyView, LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { leftMargin = dp(42) })
        val buttons = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL; setPadding(dp(42), dp(12), 0, 0) }
        buttons.addView(pillButton(getString(R.string.copy_key), filled = true) {
            getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("android-agent key", Agent.key(this)))
            Toast.makeText(this, R.string.copied, Toast.LENGTH_SHORT).show()
        })
        buttons.addView(pillButton(getString(R.string.new_key), filled = false) {
            Agent.newKey(this); Agent.record(getString(R.string.log_newkey)); refresh()
        }, LinearLayout.LayoutParams(WRAP_CONTENT, WRAP_CONTENT).apply { leftMargin = dp(10) })
        c.addView(buttons)
        c.addView(label("127.0.0.1 : ${Agent.PORT}", 13f, text2).apply { setPadding(dp(42), dp(10), 0, 0) })
        root.addView(c, lp(bottom = 22))
    }

    private fun privacyCard() {
        section(getString(R.string.privacy_title))
        val c = cardBox()
        listOf(R.string.privacy_1, R.string.privacy_2, R.string.privacy_3, R.string.privacy_4, R.string.privacy_5).forEach {
            c.addView(label(getString(it), 14f, text2).apply { setPadding(0, dp(4), 0, dp(4)); setLineSpacing(0f, 1.15f) })
        }
        root.addView(c, lp(bottom = 22))
    }

    private fun activityCard() {
        section(getString(R.string.activity_title))
        val c = cardBox()
        activityBox = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        c.addView(activityBox)
        root.addView(c, lp(bottom = 8))
    }

    // ---------- state ----------
    private fun refresh() {
        val enabled = AgentService.isEnabled(this)
        val allowed = Agent.allowed(this)
        val (color, title, sub) = when {
            enabled && allowed -> Triple(green, R.string.status_active, R.string.status_active_sub)
            enabled -> Triple(amber, R.string.status_paused, R.string.status_paused_sub)
            else -> Triple(grey, R.string.status_off, R.string.status_off_sub)
        }
        statusDot.background = circle(color)
        statusTitle.text = getString(title)
        statusSub.text = getString(sub)
        accessSwitch.isChecked = allowed
        accessSwitch.isEnabled = enabled

        for ((badge, done) in steps) {
            val ok = done()
            badge.background = circle(if (ok) green else violet)
            if (ok) badge.text = "✓"
        }
        keyView.text = Agent.key(this).chunked(4).joinToString(" ")

        activityBox.removeAllViews()
        val items = Agent.recent()
        if (items.isEmpty()) activityBox.addView(label(getString(R.string.activity_empty), 14f, text2))
        items.take(12).forEach {
            activityBox.addView(label(it, 13f, text2).apply {
                typeface = Typeface.MONOSPACE; setPadding(0, dp(3), 0, dp(3))
                maxLines = 1; ellipsize = TextUtils.TruncateAt.END
            })
        }
    }

    // ---------- small view helpers ----------
    private fun dp(v: Int) = (v * resources.displayMetrics.density).toInt()

    private fun lp(bottom: Int = 0) =
        LinearLayout.LayoutParams(MATCH_PARENT, WRAP_CONTENT).apply { bottomMargin = dp(bottom) }

    private fun label(s: String, size: Float, color: Int, bold: Boolean = false) = TextView(this).apply {
        text = s; textSize = size; setTextColor(color)
        if (bold) typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
    }

    private fun section(title: String) =
        root.addView(label(title.uppercase(), 12f, text2, bold = true).apply { letterSpacing = 0.12f; setPadding(dp(6), 0, 0, dp(10)) })

    private fun cardBox() = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        setPadding(dp(18), dp(18), dp(18), dp(18))
        background = GradientDrawable().apply { cornerRadius = dp(22).toFloat(); setColor(card); setStroke(dp(1), line) }
    }

    private fun divider() = View(this).apply {
        setBackgroundColor(line)
        layoutParams = LinearLayout.LayoutParams(MATCH_PARENT, dp(1))
    }

    private fun circle(color: Int) = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(color) }

    private fun pillButton(s: String, filled: Boolean, onClick: () -> Unit) = Button(this).apply {
        text = s; isAllCaps = false; textSize = 14f
        setTextColor(if (filled) Color.WHITE else text1)
        stateListAnimator = null
        minHeight = dp(42); minimumHeight = dp(42)
        setPadding(dp(18), 0, dp(18), 0)
        background = GradientDrawable().apply {
            cornerRadius = dp(21).toFloat()
            if (filled) setColor(violet) else { setColor(Color.TRANSPARENT); setStroke(dp(1), grey) }
        }
        setOnClickListener { onClick() }
    }
}
