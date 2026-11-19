plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android {
    namespace = "io.github.androidagent"
    compileSdk = 34

    defaultConfig {
        applicationId = "io.github.androidagent"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "0.4.0"
    }
    // Release key lives outside the repo: ~/.config/android-agent/{release.jks, keystore.pass}
    val ks = file(System.getProperty("user.home") + "/.config/android-agent/release.jks")
    val ksPass = file(System.getProperty("user.home") + "/.config/android-agent/keystore.pass")
    signingConfigs {
        if (ks.exists() && ksPass.exists()) create("release") {
            storeFile = ks
            storePassword = ksPass.readText().trim()
            keyAlias = "androidagent"
            keyPassword = ksPass.readText().trim()
        }
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = true
            isShrinkResources = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
            signingConfigs.findByName("release")?.let { signingConfig = it }
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
// No dependencies on purpose: small APK, nothing to audit but this code.
