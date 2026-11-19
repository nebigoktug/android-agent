package io.github.androidagent

import android.content.Context
import android.content.Intent
import android.graphics.Color
import android.graphics.PixelFormat
import android.graphics.drawable.GradientDrawable
import android.os.Handler
import android.os.Looper
import android.view.Gravity
import android.view.View
import android.view.WindowManager

/**
 * A small dot in the top-right corner, drawn as an accessibility overlay (no extra permission):
 *  green  = the assistant is acting right now (blinks)
 *  yellow = on and idle
 *  red    = it needs you (waiting for your OK) or something went wrong
 *  grey   = paused by you
 * Tapping it opens the app.
 */
class StatusLight(private val ctx: Context) {
    private val wm = ctx.getSystemService(WindowManager::class.java)
    private val handler = Handler(Looper.getMainLooper())
    private var view: View? = null
    private val dot = GradientDrawable().apply { shape = GradientDrawable.OVAL }
    private var tick = 0

    private val green = Color.parseColor("#19C37D")
    private val yellow = Color.parseColor("#F5B524")
    private val red = Color.parseColor("#F04438")
    private val grey = Color.parseColor("#8A8F9C")

    fun show() {
        if (view != null) return
        val d = ctx.resources.displayMetrics.density
        val size = (16 * d).toInt()
        val v = View(ctx).apply {
            background = dot
            elevation = 6 * d
            setOnClickListener {
                ctx.startActivity(Intent(ctx, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
            }
        }
        val lp = WindowManager.LayoutParams(
            size, size,
            WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY,
            WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE or WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
            PixelFormat.TRANSLUCENT
        ).apply {
            gravity = Gravity.TOP or Gravity.END
            x = (10 * d).toInt()
            y = (34 * d).toInt()
        }
        try {
            wm.addView(v, lp)
            view = v
            handler.post(loop)
        } catch (_: Exception) {
        }
    }

    fun hide() {
        handler.removeCallbacks(loop)
        view?.let { try { wm.removeView(it) } catch (_: Exception) {} }
        view = null
    }

    private val loop = object : Runnable {
        override fun run() {
            tick++
            val busy = System.currentTimeMillis() - Agent.lastActivity < 2500
            val (color, alpha) = when {
                !Agent.allowed(ctx) -> grey to 0.9f
                Agent.attention != null -> red to (if (tick % 4 < 2) 1f else 0.45f)   // slow blink
                busy -> green to (if (tick % 2 == 0) 1f else 0.55f)                   // fast blink
                else -> yellow to 0.9f
            }
            dot.setColor(color)
            dot.setStroke((1.5f * ctx.resources.displayMetrics.density).toInt(), Color.argb(200, 255, 255, 255))
            view?.alpha = alpha
            handler.postDelayed(this, 300)
        }
    }
}
