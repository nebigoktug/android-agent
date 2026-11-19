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
    buildTypes {
        getByName("release") {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"))
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
}
// No dependencies on purpose: small APK, nothing to audit but this code.
