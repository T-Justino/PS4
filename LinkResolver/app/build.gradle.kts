plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// Commit exibido no app: SHA do CI (GITHUB_SHA) ou git local.
val gitCommit: String = System.getenv("GITHUB_SHA")?.take(7)
    ?: runCatching {
        providers.exec { commandLine("git", "rev-parse", "--short", "HEAD") }.standardOutput.asText.get().trim()
    }.getOrDefault("").ifEmpty { "dev" }

android {
    namespace = "app.linkresolver"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.linkresolver"
        minSdk = 29
        targetSdk = 35
        versionCode = 2
        versionName = "0.2.0"
        buildConfigField("String", "GIT_COMMIT", "\"$gitCommit\"")
        testInstrumentationRunner = "androidx.test.runner.AndroidJUnitRunner"
    }

    buildTypes {
        release {
            isMinifyEnabled = true
            proguardFiles(getDefaultProguardFile("proguard-android-optimize.txt"), "proguard-rules.pro")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }
    buildFeatures {
        viewBinding = true
        buildConfig = true
    }
    testOptions { unitTests.isReturnDefaultValues = true }
}

dependencies {
    implementation("androidx.core:core-ktx:1.13.1")
    implementation("androidx.appcompat:appcompat:1.7.0")
    implementation("com.google.android.material:material:1.12.0")
    implementation("androidx.recyclerview:recyclerview:1.3.2")
    implementation("androidx.webkit:webkit:1.12.1")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")

    testImplementation("junit:junit:4.13.2")
    // org.json do Android é stub nos testes de unidade; esta versão real permite testar o PageScanner.
    testImplementation("org.json:json:20240303")
}
